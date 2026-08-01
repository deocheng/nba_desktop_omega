#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, json, unicodedata
BASE = "/Users/deocheng/Downloads/nba_desktop_omega_mac_migrate_2026-07-13"
PATH = os.path.join(BASE, "notes_work.json")

NEW = {
 "dwight howard": "“Superman（超人）”源自他 2008 年全明星扣篮大赛披红蓝披风、从篮板上方飞来扣篮的经典造型，他本人也是超人忠实粉丝并纹有超人图案；“D12”对应身披的 12 号。他是 3 届 DPOY、2004 年状元，2009 年单核率魔术闯入总决赛，2020 年随湖人夺冠。",
 "dwyane wade": "“Flash（闪电侠）”由热火队友奥尼尔所起——奥尼尔说灵感来自 1980 年电影《Flash Gordon》的 Queen 主题曲，形容韦德如闪电般撕裂防守；韦德起初不喜欢，却沿用终身。他还自封过“WOW（World of Wade）”。“D-Wade”为简称。他是热火队史得分王、3 届总冠军（2006、2012、2013），2006 年总决赛 MVP。",
 "earl monroe": "“The Pearl（珍珠）”源自他如珍珠般圆润流畅、令人赏心悦目的运球过人，是 70 年代尼克斯 1973 年夺冠的核心后卫；“Black Jesus（黑耶稣）”则是纽约街头球迷对他球风神性的尊称。他以颠倒换手等花式动作开创了独树一帜的“Earl the Pearl”风格。",
 "elvin hayes": "“The Big E”取自名字 Elvin 的首字母 E；他以防守与中投著称，是新秀赛季（1968-69）即夺得分王的壮汉，生涯总得分高居当时历史前列。“The Bionic Man（仿生人）”形容他似有钢铁之躯、极少伤停的耐久。他是 1978 年随子弹队夺冠的 12 届全明星。",
 "gary payton": "“The Glove（手套）”源自他如手套般紧贴、锁死对手的防守——1993 年西部决赛他成功冻结太阳后卫凯文·约翰逊，赛后表兄在电话里形容“你像棒球手套一样罩住对手”，从此得名；1996 年当选最佳防守球员，是唯一获 DPOY 的控卫。“GP”为姓名缩写。",
 "george gervin": "“Iceman（冰人）”源自 ABA 时期队友 Fatty Taylor 给他起的——因他打球从容冷静、几乎不出汗就能统治比赛，冷血终结对手；这一“冰”气质伴随他 4 届得分王、12 届全明星的辉煌。他标志性的 finger roll（手指挑篮）成为 NBA 经典技术。",
 "george mikan": "“Mr. Basketball（篮球先生）”作为 NBA 早期（40-50 年代）第一个真正的内线巨星，他重新定义了中锋位置，并直接推动了篮下干扰球判罚、三秒区加宽等规则改变（人称“Mikan Rule”）。他是明尼阿波利斯湖人 5 届总冠军核心，“Mikan the Magnificent（伟大的麦肯）”亦是其尊称。",
 "giannis antetokounmpo": "“The Greek Freak（希腊怪兽）”形容他希腊出身却拥有异于常人的臂展、步幅与全能；“The Alphabet（字母哥）”则因他超长、难拼读的姓氏 Antetokounmpo 而生。他是 2013 年首轮末段（第 15 顺位）被选中、两届 MVP（2019、2020）、2021 年率雄鹿夺冠并当选 FMVP，从移民家庭穷困少年到巨星的励志范本。",
 "grant hill": "“G-Money”为名字 Grant 缩写 G 加“Money”的俚语化昵称；他出身名门（父亲 Grant Hill Sr. 是前 NFL 跑卫），球风优雅全面，生涯早期被誉为“乔丹接班人”，1995 年与贾森·基德同获最佳新秀。“Mr. Nice（好先生）”则形容其谦谦君子形象。他是 7 届全明星，后期在太阳焕发第二春。",
 "hakeem olajuwon": "“The Dream（大梦）”源自大学（休斯顿大学）一年级时解说员 Dick Vitale 看他篮下脚步如梦似幻，遂以“Dream”相称；本名 Akeem 后也改为 Hakeem。他是两届总冠军（1994、1995）、1994 年 MVP 与 FMVP，“梦幻脚步（Dream Shake）”独步天下；“Little Moses”则呼应其名与领袖气质。",
}

def norm(s):
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return s.strip().lower()

data = {}
if os.path.exists(PATH):
    with open(PATH, encoding="utf-8") as f:
        data = json.load(f)
data.update(NEW)
with open(PATH, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print(f"已合并 {len(NEW)} 条，notes_work.json 现共 {len(data)} 条")
