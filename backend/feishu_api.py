"""按租户配置调用飞书多维表格 API。

优化说明（2026-06-10）：
- 之前每条商品查价都会向飞书发一次 HTTP 搜索，表格大时非常慢；
- 现改为「一次性拉取全表 -> 内存缓存 5 分钟 -> 本地关键词匹配」。
- 这样查 3 条 vs 100 条商品，外部 HTTP 次数都是 1。
"""

from __future__ import annotations

import re
import logging
import threading
import time
from typing import Dict, List, Optional

_perf_log = logging.getLogger("perf.match_keywords")


def _normalize(text: str) -> str:
    """文本归一化：去除空格/连字符/下划线，统一转小写。
    将 "14 plus 256G" → "14plus256g"，使拼接词匹配更鲁棒。
    """
    return re.sub(r'[\s\-_]+', '', text).lower()


def _expand_abbreviations(text: str) -> str:
    """展开型号简写：15U → 15ULTRA, X9U → X9ULTRA 等。
    仅当 U 前面是数字+可选字母，且后面不是字母/数字时展开。
    """
    return _EXPAND_ABBR_RX.sub(r'\1ULTRA', text)


_EXPAND_ABBR_RX = re.compile(r'(\w*\d+)U(?=[^A-Za-z0-9]|$)')

# _canonical_capacity 容量匹配模式（模块级编译）
_CAP_PAT = re.compile(r'(\d+)\s*(?:[gG](?:[bB])?|[tT][bB])?\s*[-+＋/]\s*(\d+)\s*(?:[gG](?:[bB])?|[tT][bB])?')


# =====================================================================
# 3C 数码【颜色属性字典】与互斥规则
# =====================================================================
# 颜色分组：每个组的颜色是互斥的，用户输入组 A 的颜色 → 结果不能包含组 B 的颜色
_COLOR_GROUPS: list[set[str]] = [
    # 黑色系 (183)
    {'Q黑', '丝绒黑', '乌木黑', '云墨黑', '亮黑色', '伏特黑', '优雅黑', '全速黑', '典雅黑', '冰峰提黑', '冰影黑', '冷夜蓝', '冷黑', '大地苔原', '动感黑', '午夜色', '午夜苍蓝', '午夜黑', '即墨', '原力黑', '可可黑', '墨岩黑', '墨晶', '墨晶黑', '墨玉青', '墨玉黑', '墨石岩黑', '墨绿', '墨羽', '墨羽黑', '墨蓝', '墨蓝瓷', '墨韵黑', '夏夜黑', '夏日乌梅', '夜', '夜幕蓝', '夜影灰', '夜影黑', '夜蓝', '夜跃黑', '太空黑', '子夜黑', '宇夜黑', '尾黑', '岩黑', '峰峦黑', '幻夜黑', '幻影墨黑', '幻影黑', '幻月黑', '悠扬乌铁', '新夜黑', '无尽黑', '无界黑', '时空黑', '昆仑黑', '星光黑', '星夜', '星夜蓝', '星夜飞行', '星夜黑', '星尘黑', '星岩黑', '星河黑', '星焰黑', '星穹黑', '星空黑', '星耀黑', '星芒黑', '星辰黑', '星野黑', '星钻黑', '星际陨黑', '星际黑', '暗夜紫', '暗夜黑', '暗影黑', '暮影黑', '曜夜黑', '曜石灰', '曜石黑', '曜金墨黑', '曜金黑', '曜黑', '月影黑', '月绒黑', '月隐黑', '朋克黑', '松烟墨', '极夜黑', '格斗黑', '棱镜黑', '橙黑色', '氘锋透明暗夜', '水墨', '水墨黑', '活力黑', '流萤黑', '浓墨色', '浩宇黑', '深岩黑', '深邃黑', '潜航黑', '熔岩黑', '燿金黑', '玄夜黑', '玄岩黑', '玄武灰', '玄武黑', '玄采', '玄黑', '琥珀黑', '疾影黑', '皓夜黑', '简黑', '瞬影黑', '石墨', '石墨灰', '石墨烯', '石墨色', '石墨黑', '石黑', '砂石黑', '砚黑', '砾石黑', '碳石黑', '碳纤黑', '磐石黑', '磨砂黑', '礁石黑', '神秘黑', '神秘黑镜', '秘影黑', '竞速黑', '素黑', '绒黑色', '缎影黑', '缎黑', '羽砂黑', '羽纱黑', '耀夜黑', '苍穹黑', '蓬勃黑', '薄翼黑', '辰夜黑', '远黛黑', '追风黑', '酷黑', '釉黑', '鎏光黑', '鎏金黑', '钛影黑', '钛空黑', '钛黑', '黑钛', '钻黑', '铂黑', '银黑', '锋雅黑', '镜中之夜', '镜夜黑', '陨石黑', '陶瓷黑', '雅丹黑', '雅瓷黑', '雅致黑', '雅黑', '雅黑色', '雨燕黑', '静夜黑', '韵律黑', '风尚黑', '魅夜紫', '魅影黑', '黑', '黑咖', '黑曜秘境', '黑玺', '黑色', '黑金', '黑金色', '黑锋', '黑黄色', '默黑'},
    # 白色系 (149)
    {'丝绒白', '云峰白', '云朵白', '云海白', '云漫白', '云白', '云绒白', '云锦白', '云雾白', '余生白首', '元气白', '光域白', '冰岛白', '冰川白', '冰晶白', '冰瓷白', '冰透白', '冰釉白', '冰雾白', '冰魄白', '凝霜白', '印象白', '哑光白', '天际白', '天光白', '奔庭白', '奔霆白', '奶油白', '宣白', '山茶白', '岩白', '幻影白', '弦乐白', '心动白', '悦动白', '新月白', '时光独白', '星云白', '星光白', '星曜白', '星沙白', '星河白', '星耀白', '星芒白', '星辉白', '星钻白', '星闪白', '星露白', '晨光白', '晨曦白', '晨白', '晨雾白', '晨霜白', '晴云白', '晴雪白', '晴霜白', '晶钻白', '暖白色', '月光白', '月岩白', '月影白', '月牙白', '月白', '柔光白', '梦境白', '棉花糖白', '樱语白', '水晶白', '沐光白', '沧浪青白', '洛可可白', '活力白', '流云白', '流光白', '流沙白', '流行白', '浮光白', '润玉白', '灵动白', '独白', '玉瓷白', '玉白', '玉露白', '珍珠白', '珠光白', '珠贝白', '瑞雪白', '电光白', '白', '白月光', '白沙银', '白色', '白色恋人', '白色手柄', '白金', '白银色', '白露晨曦', '皎月白', '皓月白', '皓白', '真皮白', '石岩白', '石英白', '破晓白', '祥云白', '米白', '羊脂白', '羽沙白', '羽砂白', '羽纱白', '羽衣白', '胖达白', '茶金白', '萱白', '象牙白', '贝壳白', '贝母白', '超跑瓷白', '轻羽白', '远峰白', '逐浪白', '釉白', '釉白色', '金星白', '鎏金白', '钻石白', '银沙白', '银翼白', '银雪白', '锦白', '镜湖白', '镜瓷白', '陶瓷白', '雪原白', '雪域白', '雪山白', '雪岩白', '雪松白', '雪玉白', '雪钻白', '雪雾白', '雪屿白', '零度白', '霜刃白', '霜白', '青霜白', '香草白', '驰光白', '骑士白', '魅族白', '鹅羽白'},
    # 灰色/钛色/银色系 (129)
    {'云影灰', '云灰', '信风灰', '先锋灰', '光织银', '冰川岩灰', '冰川灰', '冰川银', '冰川银光', '冰晶银', '冰晶银河', '冰溪银', '冰钛', '冰霜银', '冷山灰', '冷霜银', '劲酷灰', '大溪地灰', '大漠银月', '大象灰', '寒星灰', '寒武岩灰', '山岩灰', '岩灰', '岩石灰', '幻影灰', '幻影银', '引力钛', '揽月银', '新月灰', '昆仑银', '星云灰', '星光银', '星夜银', '星岩灰', '星梦银', '星河钛影', '星河银', '星空灰', '星空银', '星系银', '星耀银', '星轨亮银', '星辰灰', '星迹钛', '星钛银', '星钻银', '星银', '星际灰', '星际银', '晨雾灰', '暮光银', '暮河银', '曙光银', '月光银', '月岩灰', '月岩钛', '月影灰', '月影钛', '月蚀灰', '极光银', '极地灰', '极镜银灰', '椰子灰', '锋透明银翼', '沙漠色', '流光银', '浅灰色', '浅米灰', '深云灰', '深屿灰', '深灰', '深灰色', '深空灰', '清雅灰', '灰', '灰常好', '灰晶', '灰色', '烟云灰', '燃力钛', '玛瑙灰', '珠光灰', '皎月银', '皓月银', '皓银', '砂岩灰', '破晓灰', '秘野灰', '秘银', '纳多灰', '纳秒灰', '艺术银色', '苍山灰', '苍穹灰', '远山灰', '逐星灰', '钛', '钛岩灰', '钛影灰', '钛影银', '钛晶灰', '钛灰', '钛空橙', '钛空灰', '钛空银', '钛空镜银', '钛辉银', '钛铂银', '钛银', '钛银灰', '钛雾灰', '银月星辉', '银杏黄', '银灰', '银灰色', '银石灰', '银翼', '银翼灰', '银色', '银调', '雅柔灰', '雅灰', '丝绒灰', '雾灰', '雾茶灰', '风暴灰', '风爆灰', '骑士银', '鸽子灰'},
    # 粉色系 (62)
    {'Q绿渐粉', '云羽粉', '云霞粉', '亮粉色', '冰晶粉', '冰玫紫', '冰莓粉', '勇敢粉', '怦然粉', '星云粉', '星光粉', '晶钻粉', '极地蔷薇', '柔和桃', '柔雾粉', '桃桃粉', '桃粉', '樱玫红', '樱璃粉', '樱粉', '樱粉珊瑚', '樱花粉', '樱草金', '樱语粉', '气泡粉', '水晶粉', '流沙粉', '流莹粉', '流金粉', '浅玫粉', '浮光粉', '粉梦生花', '热爱粉', '玛瑙粉', '玫瑰星河', '玫瑰紫', '玫瑰金', '玫红', '玫红色', '珊瑚橘', '珊瑚橙', '珊瑚粉', '珊瑚紫', '珊瑚红', '粉', '粉映晨辉', '粉色', '粉蓝', '粉金', '粉金色', '莹彩粉', '落日玫瑰', '落樱粉', '蔷薇粉', '蔷薇金', '薄雾玫瑰', '蜜桃粉', '微粉', '酷莓粉', '雪山粉', '香槟粉', '马卡龙粉', '魔姬粉', '光晕粉'},
    # 蓝色系 (176)
    {'Buff蓝', 'GT蓝', '一瞬青', '云母蓝', '云水蓝', '冰川蓝', '冰晶蓝', '冰清蓝', '冰璃蓝', '冰瓷蓝', '冰羽蓝', '冰萃蓝', '冰锋蓝', '冰雪蓝', '冷川蓝', '凛蓝色', '勃朗蓝', '千峰蔚蓝', '千帆蔚蓝', '原石蓝', '图蓝', '夏沫蓝', '天境蓝', '天水碧', '天水蓝', '天海青', '天蓝色', '天际蓝', '天青', '天青灰', '天青色', '天青蓝', '天青雨', '孔雀蓝', '定胜青', '宝石蓝', '小青新', '展蓝图', '山峦青', '山野青', '岩石青', '岩雾蓝', '幻影青', '幻海蓝', '彩陶青', '影青', '微风蓝', '托帕蓝', '时光蓝', '星沙青', '星河蓝', '星海幽蓝', '星海漫航', '星海蓝', '星蓝', '星际蓝', '春潮蓝', '晓山青', '晴海蓝', '晴空海岸', '晴空蓝', '暗影蓝', '曙光蓝', '月海蓝', '松烟蓝', '极光蓝', '极光蓝莓', '极光魅海', '极地蓝海', '梅子青', '汐月蓝', '浅海蓝', '浅海贝', '浅海青', '浅湾蓝', '浅瓷蓝', '海岛蓝', '海岩灰', '海岸蓝', '海洋蓝', '海浪蓝', '海湖青', '海王星', '海蓝', '海蓝色', '海雾蓝', '海风蓝', '深宇蓝', '深海寻踪', '深海蓝', '深空蓝', '深蓝', '深蓝色', '深青色', '清风蓝', '湖光青', '溢彩蓝', '潜蓝', '灰蓝色', '烟波蓝', '烟雨青', '爵士蓝', '牛仔蓝', '瓷青', '瞬影青', '碧波微蓝', '碧波绿', '碧海青', '碧玺蓝', '碧空蓝', '竹叶青', '竹月蓝', '竹韵青', '红蓝手柄', '绣球蓝', '群青色', '自在蓝', '至臻蓝', '舒展蓝', '航海蓝', '花木蓝', '苍穹蓝', '苔原青', '茶卡青', '茶青', '萤石蓝', '蓝', '蓝宝石', '蓝朋友', '蓝梦', '蓝水翡翠', '蓝色', '蓝莓蓝', '蓝调苏打', '蓝霆', '蓝海浮光', '蔚蓝海', '薄荷蓝', '薄荷青', '藏蓝', '藏青铜色', '踏浪青', '轻舟蓝', '远山蓝', '远山青', '远海蓝', '远空蓝', '远航蓝', '追风蓝', '釉青', '钛影蓝', '钛银蓝', '钛青', '钴蓝', '锐意青', '雅川青', '雪松青', '雾凇蓝', '青', '青云平步', '青刃', '青山黛', '青峰蓝', '青提冰茶', '青松', '青灰', '青田', '青薄荷', '青雾蓝色', '凤羽青', '风羽青', '飞天青', '魅海蓝', '鲸蓝', '黛青', '龙晶蓝', '龙胆蓝', '沧浪浮光', '浮光', '星星海'},
    # 紫色系 (72)
    {'丁香紫', '云霞紫', '仙霞紫', '仲夏紫', '冰晶紫', '冰萤紫', '初号紫', '南糯紫', '天穹紫', '幻境紫', '幻影紫', '幻紫银', '幽紫秘境', '庐烟紫', '慕紫', '昆仑紫', '星云紫', '星晨紫', '星河紫', '星穹紫', '星辰紫', '晨曦紫', '普罗旺斯紫', '暮云紫', '暮光紫', '暮影', '暮紫', '极光紫', '梦幻紫', '梦幻罗兰', '槿紫', '流云紫', '流光紫', '浅茄紫', '浅薰紫', '淡紫', '淡紫色', '湛蓝紫', '灵动紫', '烟紫瓷', '烟霞紫', '玉兰紫', '砂岩紫', '紫', '紫色', '紫霞', '绒紫色', '绫罗紫', '罗兰紫', '羽砂紫', '芋紫', '莫奈紫', '菱光紫', '菱紫', '薄雾紫', '薄霞紫', '薰衣紫', '薰衣草紫色', '蝶蝶紫', '豆蔻紫', '迷蝶蓝', '迷雾灰紫', '釉下紫', '银幻紫', '银河紫', '霜紫', '霜紫色', '霞光紫', '风信紫', '飞霜紫', '香芋紫', '龙晶紫'},
    # 黄色系 (12)
    {'幻影黄', '悦动黄', '星珠黄', '星耀黄', '极速黄', '柠柚黄', '柠檬黄', '热爱黄', '能量黄', '隐耀黄', '黄', '黄色'},
    # 红色系 (24)
    {'中国红', '丹霞', '丹霞橙', '元气红', '型格红', '好运红', '安可拉红', '寰宇红', '新年红', '朱砂红', '极焰黄', '活力红', '烈焰橙', '烈焰红', '瑞红', '红', '红圈', '红白魂', '红白瑰', '红色', '赤子红', '赤柚', '赤茶橘', '釉红', '非凡洋红', '魅力红'},
    # 绿色系 (67)
    {'丝绒绿', '乔木绿', '云杉绿', '云衫绿', '仙踪绿', '冰川薄荷', '冰淇淋绿', '冰薄荷', '凝光绿', '千山绿', '千山翠', '半夏绿', '卡其绿', '原野绿', '向新绿', '型格绿', '嫩芽绿', '摩登艾绿', '旷野绿', '星云绿', '春绿', '春野绿', '月桂绿', '松叶绿', '松影绿', '松柏绿', '松石绿', '极光绿', '橄榄绿', '民谣绿', '水波绿', '洛登绿', '浅草绿', '清波翠', '清霜绿', '湖光绿', '烟青绿', '玉石绿', '玉绿色', '矿野绿', '竹影绿', '绿', '绿洲', '绿色', '绿野传奇', '绿野素青', '翡冷翠', '苍山绿', '苍绿', '苔原绿', '草木绿', '莱茵绿', '薄荷绿', '轻松银', '远山绿', '青杉绿', '青柠绿', '青榄绿', '青玉绿', '青空绿', '青葱绿', '静谧绿', '香颂绿', '鲜拧绿', '鹦鹉绿', '麦浪绿', '鼠尾草绿色'},
    # 金色系 (48)
    {'丝绒金', '云雾金', '云霞金', '光羽金', '凤羽金', '山茶金', '日志金', '明日金', '星云金', '星光金', '星耀金', '晨光金', '晨曦金', '晨辉金', '曙光金', '朝阳金', '朝霞金', '格子金', '沙漠金', '沙金色', '流光金', '流水生金', '流沙金', '流金', '浮光金', '淡金色', '灿烂金', '烁金色', '熔金', '燃速金', '琉金', '绸金', '羽砂金', '羽金', '胧月金', '釉金', '金', '金丝银锦', '金色', '金镶玉', '鎏光金', '鎏金灰', '钛金', '钴合金', '铂光金', '铂金灰', '香槟金', '鸣沙金'},
    # 橙色系 (11)
    {'好柿橙', '拉力橙', '无限橙', '星宇橙色', '橙', '橙色', '热爱橙', '熔岩橙', '燃', '燃橙色', '秘夏橙', '缤纷橙'},
    # 棕色系 (12)
    {'原色', '沙丘', '咖', '摩卡棕', '木星棕', '棕', '棕色', '沙漠驼', '浅咖色', '漠棕', '砂砾棕', '破晓棕', '褐', '马鞍棕'},
    # 彩色统称（与黑/白互斥，但兼容具体彩色）
    {"彩", "彩色", "统色"},
]

# 构建「颜色词 → 所属分组」索引
_COLOR_TO_GROUP: dict[str, int] = {}
for _gi, _g in enumerate(_COLOR_GROUPS):
    for _c in _g:
        _COLOR_TO_GROUP[_c] = _gi

# =====================================================================
# 颜色别名：拼音/英文 → 中文颜色名（支持拼音首字母、全拼、英文颜色词）
# =====================================================================
_COLOR_ALIAS_REVERSE: dict[str, str] = {
    # === 英文颜色（归一化小写形式） ===
    "black": "黑", "white": "白", "blue": "蓝", "red": "红",
    "green": "绿", "yellow": "黄", "purple": "紫", "violet": "紫",
    "pink": "粉", "gold": "金", "silver": "银色", "grey": "灰", "gray": "灰",
    "orange": "橙", "brown": "原色", "cyan": "青", "titanium": "钛银",
    "desert": "沙漠色", "midnight": "午夜黑", "starlight": "星光",
    "graphite": "石墨", "natural": "原色", "sand": "沙漠色",
    "coral": "珊瑚红", "mint": "薄荷绿", "lavender": "薰衣紫",
    "rose": "玫瑰金", "rosegold": "玫瑰金", "rosegolden": "玫瑰金",
    "spaceblack": "深空黑", "spacegrey": "深空灰", "spacegray": "深空灰",
    "sierrablue": "远峰蓝", "alpinegreen": "高山绿", "deeppurple": "暗紫",
    "midnightgreen": "午夜绿", "pacificblue": "海蓝",
    "graphite": "石墨黑", "starlight": "星光白", "natural": "原力黑",
    # === 拼音首字母缩写（支持 hs/bs/ls/ys/zs/js/fs/cs 等） ===
    "hs": "黑", "bs": "白", "ls": "绿", "ys": "银色", "zs": "紫",
    "js": "金", "fs": "粉", "cs": "橙",
    # === 拼音全拼 ===
    "hei": "黑", "bai": "白", "lv": "绿", "yin": "银色", "zi": "紫",
    "jin": "金", "fen": "粉", "hong": "红", "hui": "灰", "lan": "蓝",
    "huang": "黄", "cheng": "橙", "qing": "青", "zong": "棕",
    "shamo": "沙漠色", "tai": "钛银", "sha": "沙漠色",
    "heise": "黑", "baise": "白", "lvse": "绿", "yinse": "银色",
    "zise": "紫", "jinse": "金", "fense": "粉", "hongse": "红",
    "huise": "灰", "lanse": "蓝", "huangse": "黄", "chengse": "橙",
    "qingse": "青", "zongse": "棕",
}

# 将别名注册到 _COLOR_TO_GROUP（使 _is_color_keyword 自动识别别名）
for _alias, _chinese in _COLOR_ALIAS_REVERSE.items():
    if _chinese in _COLOR_TO_GROUP:
        _COLOR_TO_GROUP[_alias] = _COLOR_TO_GROUP[_chinese]

# 特殊分组索引（硬编码）
_GROUP_BLACK = 0   # 黑色系
_GROUP_WHITE = 1   # 白色系
_GROUP_GRAY = 2    # 灰色/钛色系
# 彩色统称（彩/彩色）—— 动态查找最后一个分组
_GROUP_GENERIC = len(_COLOR_GROUPS) - 1


def _translate_color(kw_upper: str) -> str | None:
    """将拼音/英文颜色别名翻译为中文颜色名。"""
    return _COLOR_ALIAS_REVERSE.get(kw_upper)


def _extract_color_keywords(keywords: list[str]) -> set[str]:
    """从用户关键词中提取颜色词，返回归一化后的颜色组代表词集合。
    支持拼音/英文别名自动翻译为中文颜色词（如 BLACK→黑、HS→黑）。"""
    color_set: set[str] = set()
    for kw in keywords:
        kw_norm = _normalize(kw)
        if kw_norm in _COLOR_TO_GROUP:
            # 直接命中中文颜色词
            color_set.add(kw_norm)
        else:
            # 尝试别名翻译
            translated = _COLOR_ALIAS_REVERSE.get(kw_norm)
            if translated:
                color_set.add(translated)
    return color_set


def _split_packed_color_tokens(keywords: list[str]) -> list[str]:
    """拆分粘连的汉字颜色词：粉黑金 → [..., 粉, 黑, 金]。

    当某个 keyword 是纯汉字且每个字都是已知颜色词时，拆为独立颜色。
    但如果整个词本身已经是注册的颜色（如「黑钛」「黑金」），不拆分。
    返回新的关键词列表。
    """
    result: list[str] = []
    for kw in keywords:
        if not kw or len(kw) <= 1:
            result.append(kw)
            continue
        # 如果整个词已经是已知颜色，不拆分（如「黑钛」「黑金」是完整颜色词）
        if _COLOR_TO_GROUP.get(kw) is not None:
            result.append(kw)
            continue
        if not all('\u4e00' <= ch <= '\u9fff' for ch in kw):
            result.append(kw)
            continue
        # 检查是否每个字都是已知颜色
        all_colors = True
        for ch in kw:
            if _COLOR_TO_GROUP.get(ch) is None:
                all_colors = False
                break
        if all_colors:
            # 去重顺序保留
            seen: set[str] = set()
            for ch in kw:
                if ch not in seen:
                    seen.add(ch)
                    result.append(ch)
        else:
            result.append(kw)
    return result


def _split_multi_color_keywords(keywords: list[str]) -> list[list[str]]:
    """如果关键词中包含多个颜色词，拆分为多个关键词集合（每颜色一个）。

    例如 ["A5", "活力", "12+256", "黑", "粉"] ->
         [["A5", "活力", "12+256", "黑"], ["A5", "活力", "12+256", "粉"]]

    支持拼音/英文别名：「hei、黑」会被识别为同一颜色，不会重复拆分。
    只有 0 或 1 个颜色词时，返回原列表（单元素）。
    """
    if not keywords:
        return [[]]

    # 先拆分粘连颜色词：粉黑金 → [粉, 黑, 金]
    keywords = _split_packed_color_tokens(keywords)

    # 识别颜色关键词并映射到规范化形式（去重同义别名）
    non_color_kws: list[str] = []
    canonical_colors: list[str] = []  # 去重后的中文颜色名
    seen_canonical: set[str] = set()
    # 保留原始颜色关键词（第一个出现的），用于构建拆分结果
    orig_by_canonical: dict[str, str] = {}

    for kw in keywords:
        kw_norm = _normalize(kw)
        group_id = _COLOR_TO_GROUP.get(kw_norm)
        if group_id is not None:
            # 确定规范化颜色名：优先用中文原名，其次是翻译后的
            canonical = kw_norm
            # 如果当前是别名，翻译为中文
            translated = _COLOR_ALIAS_REVERSE.get(kw_norm)
            if translated and translated in _COLOR_TO_GROUP:
                canonical = translated
            if canonical not in seen_canonical:
                seen_canonical.add(canonical)
                canonical_colors.append(canonical)
                orig_by_canonical[canonical] = kw  # 保留原始形式用于拆分
        else:
            non_color_kws.append(kw)

    if len(canonical_colors) <= 1:
        return [keywords]

    # 多个颜色 → 拆分：每个颜色独立一组，保留所有非颜色关键词
    result = []
    for c in canonical_colors:
        result.append(non_color_kws + [orig_by_canonical[c]])
    return result


def _check_color_conflict(user_color_keywords: set[str], product_name: str) -> bool:
    """检查产品名是否与用户输入的颜色要求冲突。

    「彩/彩色」统称 → 只与黑/白互斥，与具体彩色（蓝/紫/红等）兼容。

    Args:
        user_color_keywords: 用户输入中提取的颜色词（归一化后）
        product_name: 产品名称（已归一化）

    Returns:
        True 表示存在冲突（应剔除），False 表示无冲突（可保留）
    """
    if not user_color_keywords:
        return False

    # 找到用户颜色词所属的分组
    user_groups: set[int] = set()
    for ck in user_color_keywords:
        gid = _COLOR_TO_GROUP.get(ck)
        if gid is not None:
            user_groups.add(gid)

    if not user_groups:
        return False

    # 「彩/彩色」统称：只与黑/白互斥，不与具体彩色（蓝/紫/红等）冲突
    if _GROUP_GENERIC in user_groups:
        for ck, gid in _COLOR_TO_GROUP.items():
            if gid in (_GROUP_BLACK, _GROUP_WHITE):
                if ck in product_name:
                    return True
        return False

    # 具体颜色（如「蓝」）：与所有其他组的颜色互斥
    # 注意：单字中文颜色（如"红""白""黑"）容易误匹配品牌名（如"红米""黑鲨"），
    # 跳过单字颜色，仅对多字颜色（如"星辉白""子夜黑"）做冲突检查
    for ck, gid in _COLOR_TO_GROUP.items():
        if gid in user_groups:
            continue  # 同组颜色，不冲突
        # 单字中文颜色跳过，避免误匹配品牌名
        if len(ck) == 1 and '\u4e00' <= ck <= '\u9fff':
            continue
        # 对于拼音/英文别名，先翻译为中文颜色名再检查，避免别名误匹配品牌名
        # 例如 "RED" 不应匹配 "REDMI" 中的 "RED"
        check_name = ck
        translated = _COLOR_ALIAS_REVERSE.get(ck)
        if translated:
            check_name = translated
            # 翻译后的单字中文颜色也需跳过（如 "RED/HONG"→"红" 不应匹配 "红米" 品牌名）
            if len(check_name) == 1 and '\u4e00' <= check_name <= '\u9fff':
                continue
        if check_name in product_name:
            return True  # 不同组颜色 → 冲突

    return False


# =====================================================================
# 手机品牌中英文映射：英文→中文（支持大小写不敏感匹配）
# 仅包含中国数据库中使用中文名的品牌；使用英文名在数据库的品牌（如 OPPO/vivo）不在此映射中
# =====================================================================
_BRAND_EN_TO_CN: dict[str, str] = {
    "XIAOMI": "小米",
    "MI": "小米",
    "HUAWEI": "华为",
    "APPLE": "苹果",
    "IPHONE": "苹果",
    "SAMSUNG": "三星",
    "HONOR": "荣耀",
    "ONEPLUS": "一加",
    "1+": "一加",
    "REDMI": "红米",
    "MEIZU": "魅族",
    "NUBIA": "努比亚",
    "ZTE": "中兴",
    "LENOVO": "联想",
    "MOTOROLA": "摩托罗拉",
    "MOTO": "摩托罗拉",
    "SONY": "索尼",
    "NOKIA": "诺基亚",
    "BLACKBERRY": "黑莓",
    "GOOGLE": "谷歌",
    "REALME": "真我",
    "TRANSSION": "传音",
    "COOLPAD": "酷派",
    "GIONEE": "金立",
    "SHARP": "夏普",
    "PANASONIC": "松下",
    "PHILIPS": "飞利浦",
    "KONKA": "康佳",
    "HISENSE": "海信",
    "SKYWORTH": "创维",
    "CHANGHONG": "长虹",
    "HAIER": "海尔",
    "BIRD": "波导",
    "AMOI": "夏新",
    "K-TOUCH": "天语",
    "DOOV": "朵唯",
    "NEWMAN": "纽曼",
    "AUX": "奥克斯",
    "MALATA": "万利达",
    "DOPOD": "多普达",
    "SMARTISAN": "锤子",
    "8848": "8848",
    "ROG": "玩家国度",
    "XIAOLAJIAO": "小辣椒",
    "CHINA MOBILE": "中国移动",
    "AMAZON": "亚马逊",
    "OPPO": "欧珀",
    "VIVO": "维沃",
    "ACER": "宏碁",
    "ASUS": "华硕",
    "HTC": "宏达",
    "MICROSOFT": "微软",
}

# 按长度降序排列，优先匹配长品牌名（如 "OnePlus" 先于 "One"）
_BRAND_KEYS_SORTED = sorted(_BRAND_EN_TO_CN.keys(), key=lambda k: -len(k))

# 预编译单一正则模式：匹配任意品牌名（大小写不敏感），一次替换避免重复匹配
_BRAND_PATTERN = re.compile(
    '|'.join(r'\b' + re.escape(k) + r'\b' for k in _BRAND_KEYS_SORTED),
    re.IGNORECASE,
)


def translate_brand_in_text(text: str) -> str:
    """将输入文本中的英文品牌名翻译为中文品牌名（大小写不敏感）。

    使用单词边界匹配，避免 "Google Pixel" 被双重翻译为 "谷歌 谷歌"。

    示例：
        "Xiaomi 17 Black 12GB+512GB" → "小米 17 Black 12GB+512GB"
        "Redmi K80 Pro Black 16GB+1TB" → "红米 K80 Pro Black 16GB+1TB"
    """
    def _replacer(m: re.Match) -> str:
        return _BRAND_EN_TO_CN.get(m.group().upper(), m.group())
    return _BRAND_PATTERN.sub(_replacer, text)


import requests

_TOKEN_CACHE: Dict[int, tuple] = {}
_TOKEN_LOCK = threading.Lock()

# 商品全量缓存：key=hash(app_token+table_id)，value=(rows, expire_ts)
_ROWS_CACHE: Dict[int, tuple] = {}
_ROWS_LOCK = threading.Lock()
_ROWS_CACHE_TTL = 300  # 5 分钟

_FEISHU_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"


class TenantFeishuClient:
    def __init__(self, cfg):
        self.app_id = (cfg.feishu_app_id or "").strip()
        self.app_secret = (cfg.feishu_app_secret or "").strip()
        self.app_token = (cfg.feishu_app_token or "").strip()
        self.table_id = (cfg.feishu_table_id or "").strip()
        self.field_name = (cfg.feishu_field_name or "商品名称").strip()
        self.field_price = (cfg.feishu_price_field_name or "报价").strip()
        self._rows_cache_key = hash((self.app_token, self.table_id))

    # ---------- Token ----------
    def _refresh_token(self) -> Optional[str]:
        if not self.app_id or not self.app_secret:
            return None
        try:
            resp = requests.post(
                _FEISHU_TOKEN_URL,
                json={"app_id": self.app_id, "app_secret": self.app_secret},
                timeout=10,
            )
            data = resp.json()
            if data.get("code") != 0:
                return None
            token = data.get("tenant_access_token")
            expire = data.get("expire", 3600)
            _TOKEN_CACHE[hash(self.app_id)] = (token, time.time() + expire - 60)
            return token
        except Exception:
            return None

    def get_token(self) -> Optional[str]:
        key = hash(self.app_id)
        with _TOKEN_LOCK:
            cached = _TOKEN_CACHE.get(key)
            if cached and time.time() < cached[1]:
                return cached[0]
            return self._refresh_token()

    # ---------- 单元格解析 ----------
    @staticmethod
    def _as_text(cell) -> Optional[str]:
        if cell is None:
            return None
        if isinstance(cell, (list, tuple)):
            if not cell:
                return None
            cell = cell[0]
        if isinstance(cell, dict):
            for key in ("text", "value", "name", "token"):
                if key in cell and cell[key] not in (None, ""):
                    return str(cell[key])
            for _, v in cell.items():
                if isinstance(v, str) and v.strip():
                    return v
            return None
        if isinstance(cell, str):
            return cell if cell.strip() else None
        if isinstance(cell, (int, float)):
            return str(cell)
        return None

    def configured(self) -> bool:
        return bool(self.app_id and self.app_secret and self.app_token and self.table_id)

    # ---------- 全量拉取 + 缓存 ----------
    def fetch_all_rows(self, force: bool = False) -> List[dict]:
        """全量拉取当前表格，返回行记录列表。命中 5 分钟缓存。"""
        if not self.configured():
            return []
        with _ROWS_LOCK:
            cached = _ROWS_CACHE.get(self._rows_cache_key)
            if not force and cached and time.time() < cached[1]:
                return cached[0]
        rows = self._pull_all_rows()
        with _ROWS_LOCK:
            _ROWS_CACHE[self._rows_cache_key] = (rows, time.time() + _ROWS_CACHE_TTL)
        return rows

    def _pull_all_rows(self) -> List[dict]:
        token = self.get_token()
        if not token:
            return []
        url = (
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}"
            f"/tables/{self.table_id}/records"
        )
        page_token: Optional[str] = None
        rows: List[dict] = []
        try:
            while True:
                params = {"page_size": 100}
                if page_token:
                    params["page_token"] = page_token
                resp = requests.get(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    params=params,
                    timeout=120,
                )
                data = resp.json()
                if data.get("code") != 0:
                    break
                for rec in data.get("data", {}).get("items", []) or []:
                    fields = rec.get("fields", {}) or {}
                    parsed: dict = {}
                    for k, v in fields.items():
                        parsed[k] = self._as_text(v) or ""
                    rows.append(parsed)
                has_more = data.get("data", {}).get("has_more")
                page_token = data.get("data", {}).get("page_token")
                if not has_more:
                    break
        except Exception:
            return rows
        return rows

    def search_price(self, keywords: List[str]) -> tuple[Optional[str], Optional[str]]:
        """在内存缓存的全表中做关键词匹配；避免每条查价都发一次 HTTP。

        匹配策略：
          1. 命中关键词数 >= 阈值（随关键词数动态调整）
          2. 如果关键词里包含"型号词"（非容量），则必须至少命中 1 个型号词
          3. 型号词（非容量）采用"边界匹配"：关键词前后必须不是字母/数字，
             避免 "k90" 误命中 "K901"、"pro" 误命中 "Promax"。
             容量词仍用简单子串匹配，因为 "12+256" 不会被更大的数字串吃掉。
        返回 (报价, 命中的商品名称)，便于前端展示实际命中的商品名、快速调优。
        """
        rows = self.fetch_all_rows()
        return match_keywords_in_rows(rows, self.field_name, self.field_price, keywords)

    # 保留历史接口（不删，但默认不再走它）
    def _search_via_search_api(self, keywords: List[str]) -> Optional[str]:
        token = self.get_token()
        if not token or not keywords:
            return None
        url = (
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}"
            f"/tables/{self.table_id}/records/search"
        )
        try:
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                json={"query": {"must": [{"field": self.field_name, "contains": keywords[0]}]}, "highlights": False},
                timeout=15,
            )
            data = resp.json()
            if data.get("code") != 0:
                return None
            for item in data.get("data", {}).get("items", []) or []:
                fields = item.get("fields", {}) or {}
                name = self._as_text(fields.get(self.field_name)) or ""
                if not self._match_row(name, keywords):
                    continue
                price = self._as_text(fields.get(self.field_price))
                if price:
                    return price
        except Exception:
            return None
        return None

    def _search_via_list(self, keywords: List[str]) -> Optional[str]:
        # 已被 fetch_all_rows + search_price 替代；保留空实现避免外部直接调用失败
        return self.search_price(keywords)


def match_keywords_in_rows(
    rows: List[dict],
    field_name: str,
    field_price: str,
    keywords: List[str],
) -> tuple[Optional[str], Optional[str]]:
    """独立的关键词匹配函数 —— 在给定的行列表中搜索匹配项。

    供 price_service.search_price_in_cache 复用，避免重复创建 TenantFeishuClient。
    匹配逻辑与 TenantFeishuClient.search_price 完全一致。

    Returns:
        (price, matched_name)
    """
    idx, price, name = match_keywords_in_rows_with_index(rows, field_name, field_price, keywords)
    return price, name


def _precompute_row_data(rows: List[dict], field_name: str) -> tuple[list[str], list[str], list[str]]:
    """预计算每行的归一化名称、原始名称和容量，供批量匹配复用。

    Returns:
        (names_normalized, names_original, capacities)
        - names_normalized: 归一化后的商品名称列表（大写、去空格，并已翻译品牌名）
        - names_original: 原始商品名称列表（未翻译品牌名，用于 _is_real_match 边界检查）
        - capacities: 每行的 canonical 容量（如 "12+256"），无容量则为 None
    """
    names_normalized: list[str] = []
    names_original: list[str] = []
    capacities: list[str] = []

    for row in rows:
        name = row.get(field_name) or ""
        # 展开简写（如 15U→15ULTRA），避免被品牌翻译/容量提取干扰
        name = _expand_abbreviations(name)
        names_original.append(name)
        # 翻译商品名中的英文品牌为中文（如 "1+"→"一加"、"Honor"→"荣耀"），
        # 使中文品牌关键词也能匹配到使用英文/代号品牌名的商品
        name_translated = translate_brand_in_text(name)
        names_normalized.append(_normalize(name_translated))
        # 容量提取使用原始名称（品牌翻译后 "一加15-12" 会被误当容量 "15-12"）
        capacities.append(_canonical_capacity(name))

    return names_normalized, names_original, capacities


def _build_model_token_index(names_original: list[str]) -> dict[str, list[int]]:
    """构建「模型 token → 行索引列表」映射，加速匹配过滤。

    从原始商品名（带空格）中提取 model_number 模式的 token 作为索引键，
    同时将短前缀（>=3 字符）也加入索引，支持柔性匹配（如 "z10" → "Z10x"/"Z10 Turbo" 等行）。
    这样匹配时只需遍历候选行（通常 5-20 行），而非全部 9899 行。

    Returns:
        {token_lower: [row_idx, ...], ...}
        例如 {"z10x": [0,1], "z10": [0,1,10,11], ...}
    """
    index: dict[str, list[int]] = {}
    for i, name in enumerate(names_original):
        if not name:
            continue
        tokens = name.split()
        for token in tokens:
            token_lower = token.lower()
            if not token_lower:
                continue
            # 只索引 model_number 模式的 token（如 z10x, y500i, neo9）
            if not _is_model_number(token_lower):
                continue
            if token_lower not in index:
                index[token_lower] = []
            index[token_lower].append(i)
            # 同时索引短前缀（>= 3 字符），支持跨词匹配（如 "z10" → "Z10x"、"Z10 Turbo"）
            # 但避免单字符索引污染（如 "a" → 太多误匹配）
            for prefix_len in range(3, len(token_lower)):
                prefix = token_lower[:prefix_len]
                if prefix not in index:
                    index[prefix] = []
                # 去重：避免同一前缀多次索引同一行
                if not index[prefix] or index[prefix][-1] != i:
                    index[prefix].append(i)
    return index


def match_keywords_in_rows_batch(
    rows: List[dict],
    field_name: str,
    field_price: str,
    all_keywords: list[list[str]],
    price_field: Optional[str] = None,
) -> list[tuple[Optional[str], Optional[str]]]:
    """批量关键词匹配：预计算归一化数据，一次遍历处理所有行的关键词。

    Args:
        rows: 商品行列表
        field_name: 商品名称字段名
        field_price: 报价字段名
        all_keywords: 每行输入的关键词列表（与输入行一一对应）
        price_field: 可选，从 extra_json.price_map 中取指定字段的报价（如 "jg4"）

    Returns:
        [(price, matched_name, stock), ...] 与 all_keywords 等长
    """
    if not rows or not all_keywords:
        return [(None, None, None)] * len(all_keywords)

    # 预计算：一次性归一化所有商品名 + 构建模型 token 快速索引
    t_precompute = time.time()
    names_normalized, names_original, product_capacities = _precompute_row_data(rows, field_name)
    # 模型 token 索引：从原始商品名（带空格）提取 model_number 模式 token
    # 用于快速过滤候选行，将遍历从 9899 行缩小到 5-50 行
    model_index = _build_model_token_index(names_original)
    t_precompute_end = time.time()
    _perf_log.info(f"[PERF] match_keywords: precompute+index took {t_precompute_end - t_precompute:.3f}s, "
                    f"rows={len(rows)}, index_keys={len(model_index)}")

    results: list[tuple[Optional[str], Optional[str], Optional[str]]] = []

    for keywords in all_keywords:
        if not keywords:
            results.append((None, None, None))
            continue

        # ── 关键词分类/预处理 ──
        # 所有关键词统一转小写（忽略大小写）
        keywords_lower = [k.lower().strip() for k in keywords if k and k.strip()]
        if not keywords_lower:
            results.append((None, None))
            continue

        # 分类关键词
        capacity_keywords_original = [k for k in keywords if k and _is_capacity_kw(k)]
        # 容量关键词：归一化为数字格式 "12+256" 用于比较
        capacity_canonical_set: set[str] = set()
        for ck in capacity_keywords_original:
            cap = _canonical_capacity(ck)
            if cap:
                capacity_canonical_set.add(cap)
        has_capacity_keywords = bool(capacity_canonical_set)

        # 颜色关键词：使用已有的颜色提取逻辑
        color_keywords = [kw for kw in keywords_lower if _is_color_keyword(kw)]
        has_color_keywords = bool(color_keywords)
        user_colors = _extract_color_keywords(keywords)

        # 非容量、非颜色的关键词 = 型号关键词
        model_keywords: list[str] = []
        for kw in keywords_lower:
            kw_norm = _normalize(kw)
            if kw_norm in _COLOR_TO_GROUP:
                continue  # 颜色关键词
            if _is_capacity_kw(kw):
                continue  # 容量关键词
            model_keywords.append(kw_norm)
        has_model_keywords = bool(model_keywords)

        # 型号编号（如 z10/y300/a6）—— 用于快速过滤
        model_numbers = [k for k in model_keywords if _is_model_number(k)]
        primary_model_kw = (
            max(model_numbers, key=len) if model_numbers
            else max(model_keywords, key=len) if model_keywords
            else None
        )

        # 后缀关键词
        suffix_keywords = [k for k in model_keywords if k in _SUFFIX_SET]
        has_suffix_keywords = bool(suffix_keywords)

        best_price = None
        best_name = None
        best_hits = 0
        best_model_hits = -1
        best_penalty = 0
        best_idx: Optional[int] = None

        _debug_kws = ','.join(keywords) if len(keywords) <= 6 else ','.join(keywords[:6]) + '...'

        # 快速过滤：利用模型 token 索引缩小候选行范围（从 9899 → 5~50）
        candidate_indices: list[int] = model_index.get(primary_model_kw.lower(), []) if primary_model_kw and model_index else []
        if not candidate_indices:
            candidate_indices = list(range(len(rows)))

        for idx in candidate_indices:
            i = idx
            row = rows[i]
            name = names_original[i]
            if not name:
                continue
            name_lower = names_normalized[i]  # 已转小写、去空格

            # 快速过滤：主型号不在名称中（边界感知：A6 不匹配 A6V/A6l；支持 + 后缀变体）
            if primary_model_kw and not _primary_model_flexible_match(primary_model_kw, name, name_lower):
                continue

            # 颜色互斥熔断
            if user_colors and _check_color_conflict(user_colors, name_lower):
                continue

            hits = 0
            model_hit_count = 0
            has_model_hit = False
            has_capacity_hit = False
            has_color_hit = False
            primary_model_hit = False

            # ── 型号关键词匹配（子串包含，忽略大小写；后缀需精确边界） ──
            for kw_lower in model_keywords:
                if kw_lower in _SUFFIX_SET:
                    matched = _is_suffix_exact_match(kw_lower, name_lower)
                else:
                    matched = _is_real_match(kw_lower, name, name_lower)
                if matched:
                    hits += 1
                    model_hit_count += 1
                    has_model_hit = True
                    if kw_lower == primary_model_kw:
                        primary_model_hit = True
                else:
                    # AND 逻辑：型号关键词必须全部命中
                    hits = -999
                    break

            if hits < 0:
                continue

            # ── 颜色关键词匹配 ──
            for kw in color_keywords:
                color_ok = _color_match(kw, name_lower)
                if color_ok:
                    hits += 1
                    has_color_hit = True
                else:
                    # AND 逻辑：颜色关键词必须全部命中
                    hits = -999
                    break

            if hits < 0:
                continue

            # ── 容量关键词匹配（仅比较数字部分，忽略 G/GB 后缀） ──
            if has_capacity_keywords:
                product_cap = product_capacities[i]
                if product_cap and _capacity_matches(product_cap, capacity_canonical_set):
                    hits += 1
                    has_capacity_hit = True
                else:
                    # AND 逻辑：容量关键词必须命中
                    hits = -999
                    continue

            if hits <= 0:
                continue
            if has_model_keywords and not has_model_hit:
                continue
            if primary_model_kw and not primary_model_hit:
                continue
            if has_capacity_keywords and not has_capacity_hit:
                continue
            if has_color_keywords and not has_color_hit:
                continue

            # ── 后缀匹配：如果用户提供了后缀，产品必须包含（精确边界） ──
            if has_suffix_keywords:
                suffix_hit = 0
                for sk in suffix_keywords:
                    if _is_suffix_exact_match(sk, name_lower):
                        suffix_hit += 1
                if suffix_hit < len(suffix_keywords):
                    continue

            # 裸型号：未指定后缀时优先匹配不带后缀的产品
            _penalty = 0
            if not has_suffix_keywords and primary_model_kw:
                has_product_suffix = _check_product_has_suffix(name, name_lower, primary_model_kw)
                if has_product_suffix:
                    _penalty = 1

            price_val = row.get(field_price)
            if price_val is None or price_val == "":
                continue
            price = str(price_val).strip()

            if (
                hits - _penalty > best_hits
                or (hits - _penalty == best_hits and model_hit_count - _penalty > best_model_hits)
                or (hits - _penalty == best_hits and model_hit_count - _penalty == best_model_hits and best_name and len(name) < len(best_name))
                or (hits - _penalty == best_hits and not best_price)
            ):
                best_hits = hits - _penalty
                best_model_hits = model_hit_count - _penalty
                best_price = price
                best_name = name
                best_penalty = _penalty
                best_idx = i

        # ── Fallback：精确匹配失败时，放宽容量和颜色约束 ──
        if (best_price is None and (has_capacity_keywords or has_color_keywords)) or best_penalty > 0:
            # 阶段 1：放宽容量（颜色仍需匹配）
            if has_capacity_keywords:
                fallback_capacity_scores: list[tuple[int, int, float, int]] = []
                for idx in candidate_indices:
                    i = idx
                    row = rows[i]
                    name = names_original[i]
                    if not name:
                        continue
                    name_lower = names_normalized[i]

                    if primary_model_kw and not _primary_model_flexible_match(primary_model_kw, name, name_lower):
                        continue
                    if user_colors and has_color_keywords and _check_color_conflict(user_colors, name_lower):
                        continue

                    # 容量必须精确匹配（fallback 不降级内存规格）
                    if has_capacity_keywords:
                        product_cap = product_capacities[i]
                        if not product_cap or not _capacity_matches(product_cap, capacity_canonical_set):
                            continue

                    hits = 0
                    model_hit_count = 0
                    primary_model_hit = False
                    has_color_hit = not has_color_keywords
                    color_bonus = 0

                    model_all_match = True
                    for kw_lower in model_keywords:
                        if kw_lower in _SUFFIX_SET:
                            matched = _is_suffix_exact_match(kw_lower, name_lower)
                        else:
                            matched = _is_real_match(kw_lower, name, name_lower)
                        if matched:
                            hits += 1
                            model_hit_count += 1
                            if kw_lower == primary_model_kw:
                                primary_model_hit = True
                        else:
                            model_all_match = False
                            break
                    if not model_all_match:
                        continue

                    for kw in color_keywords:
                        if _color_match(kw, name_lower):
                            hits += 1
                            has_color_hit = True
                            color_bonus = 1
                            break

                    if primary_model_kw and not primary_model_hit:
                        continue
                    if hits <= 0:
                        continue
                    if has_color_keywords and not has_color_hit:
                        continue

                    if has_suffix_keywords:
                        suffix_hit = 0
                        for sk in suffix_keywords:
                            if _is_suffix_exact_match(sk, name_lower):
                                suffix_hit += 1
                        if suffix_hit < len(suffix_keywords):
                            continue

                    _penalty = 0
                    if not has_suffix_keywords and primary_model_kw:
                        has_product_suffix = _check_product_has_suffix(name, name_lower, primary_model_kw)
                        if has_product_suffix:
                            _penalty = 1

                    price_val = row.get(field_price)
                    if price_val is None or price_val == "":
                        continue
                    price = str(price_val).strip()
                    score = hits * 1000 + (model_hit_count - _penalty) * 100 + color_bonus * 10
                    best_score = best_hits * 1000 + best_model_hits * 100
                    if score > best_score or (score == best_score and not best_price):
                        best_hits = hits
                        best_model_hits = model_hit_count - _penalty
                        best_price = price
                        best_name = name
                        best_idx = i

            # 阶段 2：完全放宽，型号匹配即可
            if best_price is None:
                for idx in candidate_indices:
                    i = idx
                    row = rows[i]
                    name = names_original[i]
                    if not name:
                        continue
                    name_lower = names_normalized[i]

                    if primary_model_kw and not _primary_model_flexible_match(primary_model_kw, name, name_lower):
                        continue

                    # 容量必须精确匹配（阶段2 也不降级内存规格）
                    if has_capacity_keywords:
                        product_cap = product_capacities[i]
                        if not product_cap or not _capacity_matches(product_cap, capacity_canonical_set):
                            continue

                    hits = 0
                    model_hit_count = 0
                    primary_model_hit = False
                    color_bonus = 0

                    model_all_match = True
                    for kw_lower in model_keywords:
                        if kw_lower in _SUFFIX_SET:
                            matched = _is_suffix_exact_match(kw_lower, name_lower)
                        else:
                            matched = _is_real_match(kw_lower, name, name_lower)
                        if matched:
                            hits += 1
                            model_hit_count += 1
                            if kw_lower == primary_model_kw:
                                primary_model_hit = True
                        else:
                            model_all_match = False
                            break
                    if not model_all_match:
                        continue

                    for kw in color_keywords:
                        if _color_match(kw, name_lower):
                            color_bonus = 1
                            break
                    if has_color_keywords and color_bonus == 0:
                        continue

                    if hits <= 0:
                        continue
                    if primary_model_kw and not primary_model_hit:
                        continue

                    if has_suffix_keywords:
                        suffix_hit = 0
                        for sk in suffix_keywords:
                            if _is_suffix_exact_match(sk, name_lower):
                                suffix_hit += 1
                        if suffix_hit < len(suffix_keywords):
                            continue

                    if not has_suffix_keywords and primary_model_kw:
                        has_product_suffix = _check_product_has_suffix(name, name_lower, primary_model_kw)
                        if has_product_suffix:
                            model_hit_count = max(0, model_hit_count - 1)

                    price_val = row.get(field_price)
                    if price_val is None or price_val == "":
                        continue
                    price = str(price_val).strip()
                    _color_penalty = 500 if has_color_keywords and color_bonus == 0 else 0
                    score = hits * 1000 + model_hit_count * 100 + color_bonus * 10 - _color_penalty
                    best_score = best_hits * 1000 + best_model_hits * 100
                    if score > best_score or (score == best_score and not best_price):
                        best_hits = hits
                        best_model_hits = model_hit_count
                        best_price = price
                        best_name = name
                        best_idx = i

        # 处理 price_field（从 extra_json 取指定报价等级）
        if best_price is not None and price_field:
            for i, row in enumerate(rows):
                if names_original[i] == best_name:
                    try:
                        extra = __import__('json').loads(row.get("extra_json", "{}") or "{}")
                        pm = extra.get("price_map", {})
                        if price_field in pm and pm[price_field]:
                            best_price = pm[price_field]
                    except Exception:
                        pass
                    break

        # 提取库存数量
        stock_value: Optional[str] = None
        if best_idx is not None:
            try:
                extra = __import__('json').loads(rows[best_idx].get("extra_json", "{}") or "{}")
                sv = extra.get("库存数量", "")
                stock_value = str(sv).strip() if sv is not None else None
            except Exception:
                pass

        results.append((best_price, best_name, stock_value))

    _perf_log.info(f"[PERF] match_keywords: per-keyword matching took {time.time() - t_precompute_end:.3f}s, "
                    f"for {len(all_keywords)} keyword sets")
    return results


# 已知的型号后缀：允许关键词匹配到型号+后缀中（如 K80 匹配 K80Pro）
_MODEL_SUFFIXES = sorted([
    'promax', 'proplus', 'pro+', 'pro',
    'ultra', 'max+', 'max',
    'plus+', 'plus',
    'lite+', 'lite',
    'turbo+', 'turbo',
    'neo', 'se', 'gt', 'note', 'play', 'youth', 's',
    '活力版', '至尊版', '公开版', '移动版',
], key=lambda s: -len(s))

# 后缀集合（用于快速查找）
_SUFFIX_SET: set[str] = set(_MODEL_SUFFIXES)

# 后缀前缀关系：{prefix_suffix: {longer_suffixes_that_start_with_it}}
# turbo → turbo+, pro → pro+/proplus/promax, plus → plus+, max → max+, lite → lite+
_SUFFIX_PREFIX_MAP: dict[str, set[str]] = {}
for _s in _MODEL_SUFFIXES:
    for _t in _MODEL_SUFFIXES:
        if _t != _s and _t.startswith(_s):
            _SUFFIX_PREFIX_MAP.setdefault(_s, set()).add(_t)


def _is_suffix_exact_match(sk: str, name_lower: str) -> bool:
    """检查后缀关键词是否精确匹配，而非作为更长后缀的前缀。

    例如：turbo 不应匹配 turbo+（因为 turbo+ 是另一个独立后缀）。
    """
    if sk not in _SUFFIX_PREFIX_MAP:
        return sk in name_lower  # 无歧义的后缀，简单子串匹配即可
    # 先找到 sk 的位置，再检查是否有更长后缀在此开始
    pos = 0
    while True:
        pos = name_lower.find(sk, pos)
        if pos == -1:
            return False
        # 检查该位置是否匹配了更长的后缀
        longer_suffixes = _SUFFIX_PREFIX_MAP[sk]
        is_partial = False
        for longer in longer_suffixes:
            if name_lower[pos:pos + len(longer)] == longer:
                is_partial = True
                break
        if not is_partial:
            return True
        pos += 1  # 继续搜索下一个可能的位置
    return False

_MODEL_NUMBER_RE = re.compile(r'^[A-Za-z]+\d+[A-Za-z+]*$')

def _is_model_number(kw: str) -> bool:
    """判断关键词是否为型号编号（如 Z10/A6/Y300/NOTE15/K13），而非通用后缀。
    用于选择 primary_model_kw，避免 TURBO/PRO 等后缀成为主关键词。"""
    return bool(_MODEL_NUMBER_RE.match(kw))


def _check_product_has_suffix(name_orig: str, name_up: str, model_kw: str) -> bool:
    """检查产品名中，型号编号后面是否跟了已知后缀（如 GT/PRO/PRO+ 等）。
    用于在裸型号匹配时，优先选择不带后缀的产品。"""
    # 在归一化名称中查找型号关键词
    idx = name_up.find(model_kw)
    if idx < 0:
        return False
    end = idx + len(model_kw)
    if end >= len(name_up):
        return False
    after = name_up[end:]
    # 容量规格不算后缀
    if re.match(r'^\d+(?:[gG](?:[bB])?|[tT][bB])?[+＋]', after):
        return False
    return any(after.startswith(s) for s in _SUFFIX_SET)


def _primary_model_flexible_match(primary_kw: str, name_orig: str, name_lower: str) -> bool:
    """主型号柔性匹配：支持 + 后缀变体。

    例如 primary_kw='z10turbo+' 可以匹配 DB 中的 'z10 turbo'，
    因为 DB 中 'turbo' 不带 + 但型号主体相同。
    """
    if _is_real_match(primary_kw, name_orig, name_lower):
        return True
    # 末尾带 + 的型号，尝试去掉 + 再匹配
    # （如 z10turbo+ → z10turbo，DB 中可能是 z10 turbo）
    if primary_kw.endswith('+'):
        kw_no_plus = primary_kw.rstrip('+')
        if kw_no_plus and _is_real_match(kw_no_plus, name_orig, name_lower):
            return True
    # 末尾带 + 后缀，也尝试匹配带空格分割的型号
    # （如 z10turbo+ → 先匹配 z10 再看 turbo+）
    return False


def _is_real_match(kw_upper: str, name_orig: str, name_up: str = '') -> bool:
    """边界感知匹配：防止「note14」误匹配「note14pro」或「note145」。

    对于纯 ASCII 字母数字关键词（如 A5、Z10TURBO），要求匹配位置后面
    不能紧跟字母或数字。中文关键词（如「活力版」「子夜黑」）不受此限制。

    例外：若紧跟的字符是已知型号后缀（Pro/Max/Ultra/+/活力版 等），视为合法匹配。
    例如 K80 允许匹配 K80Pro、K80ProMax。

    后缀精确匹配：PRO 不匹配 PRO+、PROMAX；TURBO 不匹配 TURBOPRO。
    例如用户输入「Y300Pro」应匹配 Y300Pro 而非 Y300Pro+。

    先在原始名称中查找，若找不到（因空格分隔导致），回退到归一化名称。
    归一化名称中，若关键词后紧跟容量规格（如 12+256），视为合法匹配。
    若归一化名称中仍找不到（因品牌翻译「1+」→「一加」），回退到 name_up。
    """
    # 后缀关键词精确匹配辅助
    def _suffix_boundary_check(end_pos: int, text: str) -> bool:
        """当关键词本身是后缀（PRO/TURBO/PRO+等）时，确保不会匹配到更长的后缀。"""
        if kw_upper not in _SUFFIX_SET:
            return True  # 不是后缀，不检查
        if end_pos >= len(text):
            return True  # 关键词在末尾，合法
        next_ch = text[end_pos]
        # 后面紧跟字母/数字/+ → 可能是更长的后缀（PRO→PRO+、TURBO→TURBOPRO）
        if next_ch.isascii() and (next_ch.isalnum() or next_ch == '+'):
            return False
        return True

    name_lower = name_orig.lower()
    idx = name_lower.find(kw_upper)
    # 在原始名中找不到（可能被空格分隔，如 "Z10 Turbo"），尝试归一化名
    if idx < 0:
        name_norm = _normalize(name_orig)
        idx = name_norm.find(kw_upper)
        # 归一化后仍找不到（如品牌翻译 "1+"→"一加"），尝试已翻译的名称
        if idx < 0 and name_up:
            idx = name_up.find(kw_upper)
            if idx < 0:
                return False
            # 中文关键词（品牌名翻译后）从不需要边界检查
            return True
        if idx < 0:
            return False
        # 只有纯 ASCII 字母数字关键词才需要边界检查（中文如「活力版」不需要）
        if not kw_upper.isascii():
            return True
        end = idx + len(kw_upper)
        if end < len(name_norm):
            next_char = name_norm[end]
            # 只有 ASCII 字母/数字才触发边界检查（中文字符如「活力版」「星辉白」不应拦截）
            if next_char.isascii() and next_char.isalnum():
                # 后面紧跟字母或数字 → 检查是否为容量规格（如 12+256 或 12gb+512gb）
                after = name_norm[end:]
                if re.match(r'^\d+(?:[gG](?:[bB])?|[tT][bB])?[+＋]', after):
                    return True  # 容量规格，合法匹配
                # 后缀精确匹配：PRO 不匹配 PRO+、TURBO 不匹配 TURBOPRO
                if not _suffix_boundary_check(end, name_norm):
                    return False
                # 检查是否为已知型号后缀（如 K80→K80Pro）
                after_lower = after.lower()
                if any(after_lower.startswith(s) for s in _MODEL_SUFFIXES):
                    return True
                return False
            # 处理 "+" 等非字母数字字符（PRO → PRO+）
            if next_char == '+' and not _suffix_boundary_check(end, name_norm):
                return False
        return True
    # 只有纯 ASCII 字母数字关键词才需要边界检查（中文如「活力版」不需要）
    if not kw_upper.isascii():
        return True
    end = idx + len(kw_upper)
    if end < len(name_lower):
        next_char = name_lower[end]
        # 后面紧跟 ASCII 字母或数字 → 是另一个型号的前缀，不算真正匹配
        if next_char.isascii() and next_char.isalnum():
            # 后缀精确匹配：PRO 不匹配 PRO+、TURBO 不匹配 TURBOPRO
            if not _suffix_boundary_check(end, name_lower):
                return False
            # 检查是否为已知型号后缀（如 K80→K80Pro）
            after = name_lower[end:]
            if any(after.lower().startswith(s) for s in _MODEL_SUFFIXES):
                return True
            return False
        # 处理 "+" 等非字母数字字符（PRO → PRO+）
        if next_char == '+' and not _suffix_boundary_check(end, name_lower):
            return False
    return True


def _is_color_keyword(kw: str) -> bool:
    """判断关键词是否为颜色词（归一化后）。"""
    return _normalize(kw) in _COLOR_TO_GROUP


def _color_match(kw_upper: str, name_up: str) -> bool:
    """颜色匹配：先翻译拼音/英文别名，再精确匹配，失败时尝试同组匹配。

    例如「星河银」在「星空银」中找不到精确子串，但同属灰色/银色组，应视为匹配。
    又如「BLACK」先翻译为「黑」，再与产品名中的「黑」系列颜色匹配。
    """
    # 翻译别名（如 BLACK→黑、HS→黑）
    translated = _COLOR_ALIAS_REVERSE.get(kw_upper)
    color = translated if translated else kw_upper

    if color in name_up:
        return True
    # 回退：同组匹配
    user_group = _COLOR_TO_GROUP.get(color)
    if user_group is None:
        return False
    for color_name, group_id in _COLOR_TO_GROUP.items():
        if group_id == user_group and _normalize(color_name) in name_up:
            return True
    return False


def match_keywords_in_rows_with_index(
    rows: List[dict],
    field_name: str,
    field_price: str,
    keywords: List[str],
) -> tuple[Optional[int], Optional[str], Optional[str]]:
    """与 match_keywords_in_rows 相同，但额外返回匹配行的索引。

    Returns:
        (index, price, matched_name)
    """
    if not rows or not keywords:
        return None, None, None

    # ── 关键词分类/预处理（统一转小写） ──
    keywords_lower = [k.lower().strip() for k in keywords if k and k.strip()]
    if not keywords_lower:
        return None, None, None

    # 容量关键词：归一化为数字格式
    capacity_canonical_set: set[str] = set()
    for ck in keywords:
        cap = _canonical_capacity(ck) if _is_capacity_kw(ck) else None
        if cap:
            capacity_canonical_set.add(cap)
    has_capacity_keywords = bool(capacity_canonical_set)

    # 颜色关键词
    color_keywords = [kw for kw in keywords_lower if _is_color_keyword(kw)]
    has_color_keywords = bool(color_keywords)
    user_colors = _extract_color_keywords(keywords)

    # 型号关键词（非容量、非颜色）
    model_keywords: list[str] = []
    for kw in keywords_lower:
        kw_norm = _normalize(kw)
        if kw_norm in _COLOR_TO_GROUP:
            continue
        if _is_capacity_kw(kw):
            continue
        model_keywords.append(kw_norm)
    has_model_keywords = bool(model_keywords)

    model_numbers = [k for k in model_keywords if _is_model_number(k)]
    primary_model_kw = (
        max(model_numbers, key=len) if model_numbers
        else max(model_keywords, key=len) if model_keywords
        else None
    )

    suffix_keywords = [k for k in model_keywords if k in _SUFFIX_SET]
    has_suffix_keywords = bool(suffix_keywords)

    best_price: Optional[str] = None
    best_name: Optional[str] = None
    best_idx: Optional[int] = None
    best_hits = 0
    best_model_hits = -1
    best_penalty = 0

    for i, row in enumerate(rows):
        name = row.get(field_name) or ""
        if not name:
            continue
        name = _expand_abbreviations(name)
        name_translated = translate_brand_in_text(name)
        name_lower = _normalize(name_translated)

        if primary_model_kw and not _primary_model_flexible_match(primary_model_kw, name, name_lower):
            continue
        if user_colors and _check_color_conflict(user_colors, name_lower):
            continue

        hits = 0
        model_hit_count = 0
        has_model_hit = False
        has_capacity_hit = False
        has_color_hit = False
        primary_model_hit = False

        # 型号关键词（子串包含；后缀需精确边界，普通型号需边界检测）
        for kw_lower in model_keywords:
            if kw_lower in _SUFFIX_SET:
                matched = _is_suffix_exact_match(kw_lower, name_lower)
            else:
                matched = _is_real_match(kw_lower, name, name_lower)
            if matched:
                hits += 1
                model_hit_count += 1
                has_model_hit = True
                if kw_lower == primary_model_kw:
                    primary_model_hit = True
            else:
                hits = -999
                break
        if hits < 0:
            continue

        # 颜色关键词
        for kw in color_keywords:
            if _color_match(kw, name_lower):
                hits += 1
                has_color_hit = True
            else:
                hits = -999
                break
        if hits < 0:
            continue

        # 容量关键词（只比较数字）
        if has_capacity_keywords:
            product_cap = _canonical_capacity(name)
            if product_cap and _capacity_matches(product_cap, capacity_canonical_set):
                hits += 1
                has_capacity_hit = True
            else:
                hits = -999
                continue

        if hits <= 0:
            continue
        if has_model_keywords and not has_model_hit:
            continue
        if primary_model_kw and not primary_model_hit:
            continue
        if has_capacity_keywords and not has_capacity_hit:
            continue
        if has_color_keywords and not has_color_hit:
            continue

        if has_suffix_keywords:
            suffix_hit = 0
            for sk in suffix_keywords:
                if _is_suffix_exact_match(sk, name_lower):
                    suffix_hit += 1
            if suffix_hit < len(suffix_keywords):
                continue

        _penalty = 0
        if not has_suffix_keywords and primary_model_kw:
            has_product_suffix = _check_product_has_suffix(name, name_lower, primary_model_kw)
            if has_product_suffix:
                _penalty = 1

        price_val = row.get(field_price)
        if price_val is None or price_val == "":
            continue
        price = str(price_val).strip()
        if (
            hits - _penalty > best_hits
            or (hits - _penalty == best_hits and model_hit_count - _penalty > best_model_hits)
            or (hits - _penalty == best_hits and model_hit_count - _penalty == best_model_hits and best_name and len(name) < len(best_name))
            or (hits - _penalty == best_hits and not best_price)
        ):
            best_hits = hits - _penalty
            best_model_hits = model_hit_count - _penalty
            best_price = price
            best_name = name
            best_idx = i
            best_penalty = _penalty

    # ── Fallback：放宽约束 ──
    if (best_price is None and (has_capacity_keywords or has_color_keywords)) or best_penalty > 0:
        if has_capacity_keywords:
            for i, row in enumerate(rows):
                name = row.get(field_name) or ""
                if not name:
                    continue
                name = _expand_abbreviations(name)
                name_translated = translate_brand_in_text(name)
                name_lower = _normalize(name_translated)

                if primary_model_kw and not _primary_model_flexible_match(primary_model_kw, name, name_lower):
                    continue
                if user_colors and has_color_keywords and _check_color_conflict(user_colors, name_lower):
                    continue

                # 容量必须精确匹配（fallback 不降级内存规格）
                if has_capacity_keywords:
                    product_cap = _canonical_capacity(name)
                    if not product_cap or not _capacity_matches(product_cap, capacity_canonical_set):
                        continue

                hits = 0
                model_hit_count = 0
                primary_model_hit = False
                has_color_hit = not has_color_keywords
                color_bonus = 0

                model_all_match = True
                for kw_lower in model_keywords:
                    if kw_lower in _SUFFIX_SET:
                        matched = _is_suffix_exact_match(kw_lower, name_lower)
                    else:
                        matched = _is_real_match(kw_lower, name, name_lower)
                    if matched:
                        hits += 1
                        model_hit_count += 1
                        if kw_lower == primary_model_kw:
                            primary_model_hit = True
                    else:
                        model_all_match = False
                        break
                if not model_all_match:
                    continue

                for kw in color_keywords:
                    if _color_match(kw, name_lower):
                        hits += 1
                        has_color_hit = True
                        color_bonus = 1
                        break

                if primary_model_kw and not primary_model_hit:
                    continue
                if hits <= 0:
                    continue
                if has_color_keywords and not has_color_hit:
                    continue

                if has_suffix_keywords:
                    suffix_hit = 0
                    for sk in suffix_keywords:
                        if _is_suffix_exact_match(sk, name_lower):
                            suffix_hit += 1
                    if suffix_hit < len(suffix_keywords):
                        continue

                _penalty = 0
                if not has_suffix_keywords and primary_model_kw:
                    has_product_suffix = _check_product_has_suffix(name, name_lower, primary_model_kw)
                    if has_product_suffix:
                        _penalty = 1

                price_val = row.get(field_price)
                if price_val is None or price_val == "":
                    continue
                price = str(price_val).strip()
                score = hits * 1000 + (model_hit_count - _penalty) * 100 + color_bonus * 10
                best_score = best_hits * 1000 + best_model_hits * 100
                if score > best_score or (score == best_score and not best_price):
                    best_hits = hits
                    best_model_hits = model_hit_count - _penalty
                    best_price = price
                    best_name = name
                    best_idx = i

        if best_price is None:
            for i, row in enumerate(rows):
                name = row.get(field_name) or ""
                if not name:
                    continue
                name = _expand_abbreviations(name)
                name_translated = translate_brand_in_text(name)
                name_lower = _normalize(name_translated)

                if primary_model_kw and not _primary_model_flexible_match(primary_model_kw, name, name_lower):
                    continue

                # 容量必须精确匹配（阶段2 也不降级内存规格）
                if has_capacity_keywords:
                    product_cap = _canonical_capacity(name)
                    if not product_cap or not _capacity_matches(product_cap, capacity_canonical_set):
                        continue

                hits = 0
                model_hit_count = 0
                primary_model_hit = False
                color_bonus = 0

                model_all_match = True
                for kw_lower in model_keywords:
                    if kw_lower in _SUFFIX_SET:
                        matched = _is_suffix_exact_match(kw_lower, name_lower)
                    else:
                        matched = _is_real_match(kw_lower, name, name_lower)
                    if matched:
                        hits += 1
                        model_hit_count += 1
                        if kw_lower == primary_model_kw:
                            primary_model_hit = True
                    else:
                        model_all_match = False
                        break
                if not model_all_match:
                    continue

                for kw in color_keywords:
                    if _color_match(kw, name_lower):
                        color_bonus = 1
                        break
                if has_color_keywords and color_bonus == 0:
                    continue

                if hits <= 0:
                    continue
                if primary_model_kw and not primary_model_hit:
                    continue

                if has_suffix_keywords:
                    suffix_hit = 0
                    for sk in suffix_keywords:
                        if _is_suffix_exact_match(sk, name_lower):
                            suffix_hit += 1
                    if suffix_hit < len(suffix_keywords):
                        continue

                if not has_suffix_keywords and primary_model_kw:
                    has_product_suffix = _check_product_has_suffix(name, name_lower, primary_model_kw)
                    if has_product_suffix:
                        model_hit_count = max(0, model_hit_count - 1)

                price_val = row.get(field_price)
                if price_val is None or price_val == "":
                    continue
                price = str(price_val).strip()
                _color_penalty = 500 if has_color_keywords and color_bonus == 0 else 0
                score = hits * 1000 + model_hit_count * 100 + color_bonus * 10 - _color_penalty
                best_score = best_hits * 1000 + best_model_hits * 100
                if score > best_score or (score == best_score and not best_price):
                    best_hits = hits
                    best_model_hits = model_hit_count
                    best_price = price
                    best_name = name
                    best_idx = i

    return best_idx, best_price, best_name


# 提取为模块级函数，供 match_keywords_in_rows 复用
def _is_capacity_kw(kw: str) -> bool:
    """判断是否是「容量类」关键词。

    支持所有常见容量书写格式：
      - 12+512, 12+512G, 12+512GB, 12GB+512GB, 12G+512G
      - 12-512, 12-512G, 12/512, 12 512
      - 12G运行内存+512G机身存储, 12G运存+512G内存, 12G RAM+512G ROM
      - 512GB+12GB（倒序）
      - 12GB & 512GB, 12GB / 512GB
    """
    if not kw:
        return False
    return _canonical_capacity(kw) is not None


def _canonical_capacity(text: str) -> str | None:
    """从任意容量文本中提取并归一化为标准格式 '12+512' 或 '16+1TB'。

    支持所有常见格式（见 _is_capacity_kw 文档），返回 None 表示不是容量。
    TB 容量不交换顺序且保留 TB 后缀，因 1TB 实际容量远大于 16GB。

    当文本中有多个疑似容量匹配时（如「x70-12+512G」中 70-12 和 12+512G），
    优先选择带 GB/G/TB 后缀的匹配，避免误提取型号中的数字组合。
    """
    if not text:
        return None
    has_tb = bool(re.search(r'[tT][bB]', text))
    # 0) 收集所有容量匹配，优先选择带单位后缀的（避免误匹配型号数字）
    #    使用手动扫描（而非 finditer），因 finditer 只返回非重叠匹配，
    #    而「x70-12+512G」中 70-12 和 12+512G 重叠（共享数字"12"）。
    #    跳过前一个字符也是数字的位置，避免「12+256」被拆出「2+256」假匹配。
    all_matches: list[re.Match] = []
    pos = 0
    text_len = len(text)
    while pos < text_len:
        # 快速跳过非数字字符
        if not text[pos].isdigit():
            pos += 1
            continue
        # 跳过数字内部位置（前面也是数字），避免「12」被拆出「2」
        if pos > 0 and text[pos - 1].isdigit():
            pos += 1
            continue
        m = _CAP_PAT.match(text, pos)
        if m:
            # 跳过品牌 "1+" 伪匹配
            is_oneplus = (
                (m.start() == 0 and (text.startswith('1+') or text.startswith('1＋')))
                or (m.start() >= 2 and text[m.start()-2:m.start()] in ('1+', '1＋'))
            )
            if not is_oneplus:
                all_matches.append(m)
            pos = m.start() + 1  # 前进一位，允许重叠匹配
        else:
            pos += 1

    if not all_matches:
        m = None
    elif len(all_matches) == 1:
        m = all_matches[0]
    else:
        # 多个匹配时：优先选带 GB/G/TB 后缀的（更可能是真实容量）
        best_score = -1
        best_m = all_matches[0]
        for match in all_matches:
            score = 0
            matched = match.group(0)
            # GB/G 后缀加分
            if re.search(r'[gG][bB]?', matched):
                score += 100
            # TB 后缀加分
            if re.search(r'[tT][bB]', matched):
                score += 200
            # 靠近文本末尾加分（容量通常在尾部）
            score += match.start()  # 越靠后分值越高
            if score > best_score:
                best_score = score
                best_m = match
        m = best_m
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if not has_tb and a > b:
            a, b = b, a
        if has_tb:
            return f"{a}+{b}TB"
        return f"{a}+{b}"
    # 1) 去掉空格
    cleaned = re.sub(r'\s+', '', text)
    # 1.5) 将 & 替换为 +，统一分隔符
    cleaned = cleaned.replace('&', '+')
    # 2) 去掉 GB/G/gb/g 后缀（但只在容量表达式内部移除，即后面跟着 + 或字符串结尾）
    #    避免错误移除 "12+512GB流光白" 中的 GB（后面是中文，不是容量单位）
    #    TB 后缀保留不删除（TB 值与 GB 数量级不同，不可直接比较数字大小）
    if has_tb:
        cleaned = re.sub(r'[gG][bB]?(?=\+|$)', '', cleaned)
    else:
        cleaned = re.sub(r'(?:[gG][bB]?|[tT][bB])(?=\+|$)', '', cleaned)
    # 3) 去掉中文描述和英文描述（运行内存、运存、内存、机身存储、RAM、ROM、大内存等）
    cleaned = re.sub(
        r'运行内存|运存|机身存储|大内存|内存|RAM|ROM',
        '', cleaned, flags=re.IGNORECASE,
    )
    # 4) 寻找「数字 分隔符 数字」的容量模式
    m = re.search(r'(\d+)[-+＋/](\d+)', cleaned)
    if not m:
        # 单数字容量：LLM 可能仅拆分出存储容量（如 "256"/"128"/"512"），不带运行内存
        # 常见手机存储容量: 16/32/64/128/256/512/1024
        # 1) 纯数字输入（如 LLM 拆分出的 "256"）
        m_standalone = re.match(r'^(\d+)$', cleaned)
        if m_standalone:
            num = int(m_standalone.group(1))
            if num in (16, 32, 64, 128, 256, 512, 1024):
                return f"*+{num}"
        # 2) 产品名中「数字G/GB」格式（如 "256G"、"128GB"）— 无运行内存配对
        m_standalone = re.search(r'(?<!\d)(16|32|64|128|256|512|1024)\s*[gG][bB]?(?!\d)', cleaned)
        if m_standalone:
            num = int(m_standalone.group(1))
            return f"*+{num}"
        return None
    a, b = int(m.group(1)), int(m.group(2))
    # 规范化：RAM（小数字）在前，ROM（大数字）在后
    if not has_tb and a > b:
        a, b = b, a
    if has_tb:
        return f"{a}+{b}TB"
    return f"{a}+{b}"


def _capacity_matches(product_cap: str, user_caps: set[str]) -> bool:
    """检查产品容量是否匹配用户容量集合（支持 *+ 通配符）。
    
    常规匹配：product_cap="12+256" vs user_caps={"12+256"} → 精确匹配
    通配符匹配：product_cap="8+128" vs user_caps={"*+128"} → 匹配（产品包含 128G 存储）
    *+ 表示「不关心运行内存，只要存储容量匹配」
    """
    for uc in user_caps:
        if uc == product_cap:
            return True
        if uc.startswith('*+'):
            storage = uc[2:]
            parts = product_cap.split('+')
            if len(parts) == 2 and storage in parts:
                return True
    return False


def _match_threshold(keywords: List[str]) -> int:
    """一行需要命中多少个关键词才算「匹配」。"""
    if not keywords:
        return 1
    if len(keywords) <= 2:
        return 1
    if len(keywords) <= 4:
        return 2
    return 3
