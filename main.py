from asyncio import as_completed
import os
import re
import time
import uuid
import hashlib
import logging
import secrets
import threading
from datetime import datetime, timedelta
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import requests
from bs4 import BeautifulSoup
import yt_dlp
from ddgs import DDGS

# --- PyInstaller resource path fix ---
import sys
from pathlib import Path as _Path
def resource_path(relative):
    """يعيد المسار الصحيح للملفات سواء عند التشغيل العادي او داخل الـ EXE"""
    try:
        base = _Path(sys._MEIPASS)  # داخل الـ EXE
    except AttributeError:
        base = _Path(__file__).parent
    return str(base / relative)

# حمّل .env من المسار الصحيح
load_dotenv(dotenv_path=resource_path(".env"))
# fallback للمسار العادي ايضا
if not os.getenv("TMDB_API_KEY"):
    load_dotenv()

logging.basicConfig(
    filename="app.log", level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

TMDB_API_KEY = os.getenv("TMDB_API_KEY", "")
ACCESS_PASSWORD = os.getenv("ACCESS_PASSWORD", "admin123")
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "adminsecret")
SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_hex(32))
DAILY_SEARCH_LIMIT = int(os.getenv("DAILY_SEARCH_LIMIT", "50"))
DAILY_DOWNLOAD_LIMIT = int(os.getenv("DAILY_DOWNLOAD_LIMIT", "50"))
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", os.path.join(os.path.expanduser("~"), "Downloads"))

active_tokens = {}
usage_tracker = defaultdict(lambda: {"searches": 0, "downloads": 0, "reset_date": datetime.now().strftime("%Y-%m-%d")})
api_keys_store = {
    "PREMIUM-DEMO-001": {"plan": "monthly", "expires": "2027-12-31", "daily_downloads": 50, "active": True},
}

search_cache = {}
CACHE_TTL = 300

active_downloads = {}
download_lock = threading.Lock()
current_download_dir = DOWNLOAD_DIR

SURAHS = [
    (1,"Al-Fatihah",7,"Makkiyah"),(2,"Al-Baqarah",286,"Madaniyah"),(3,"Ali Imran",200,"Madaniyah"),
    (4,"An-Nisa",176,"Madaniyah"),(5,"Al-Maidah",120,"Madaniyah"),(6,"Al-Anam",165,"Makkiyah"),
    (7,"Al-Araf",206,"Makkiyah"),(8,"Al-Anfal",75,"Madaniyah"),(9,"At-Tawbah",129,"Madaniyah"),
    (10,"Yunus",109,"Makkiyah"),(11,"Hud",123,"Makkiyah"),(12,"Yusuf",111,"Makkiyah"),
    (13,"Ar-Rad",43,"Madaniyah"),(14,"Ibrahim",52,"Makkiyah"),(15,"Al-Hijr",99,"Makkiyah"),
    (16,"An-Nahl",128,"Makkiyah"),(17,"Al-Isra",111,"Makkiyah"),(18,"Al-Kahf",110,"Makkiyah"),
    (19,"Maryam",98,"Makkiyah"),(20,"Ta-Ha",135,"Makkiyah"),(21,"Al-Anbiya",112,"Makkiyah"),
    (22,"Al-Hajj",78,"Madaniyah"),(23,"Al-Muminun",118,"Makkiyah"),(24,"An-Nur",64,"Madaniyah"),
    (25,"Al-Furqan",77,"Makkiyah"),(26,"Ash-Shuara",227,"Makkiyah"),(27,"An-Naml",93,"Makkiyah"),
    (28,"Al-Qasas",88,"Makkiyah"),(29,"Al-Ankabut",69,"Makkiyah"),(30,"Ar-Rum",60,"Makkiyah"),
    (31,"Luqman",34,"Makkiyah"),(32,"As-Sajdah",30,"Makkiyah"),(33,"Al-Ahzab",73,"Madaniyah"),
    (34,"Saba",54,"Makkiyah"),(35,"Fatir",45,"Makkiyah"),(36,"Ya-Sin",83,"Makkiyah"),
    (37,"As-Saffat",182,"Makkiyah"),(38,"Sad",88,"Makkiyah"),(39,"Az-Zumar",75,"Makkiyah"),
    (40,"Ghafir",85,"Makkiyah"),(41,"Fussilat",54,"Makkiyah"),(42,"Ash-Shura",53,"Makkiyah"),
    (43,"Az-Zukhruf",89,"Makkiyah"),(44,"Ad-Dukhan",59,"Makkiyah"),(45,"Al-Jathiyah",37,"Makkiyah"),
    (46,"Al-Ahqaf",35,"Makkiyah"),(47,"Muhammad",38,"Madaniyah"),(48,"Al-Fath",29,"Madaniyah"),
    (49,"Al-Hujurat",18,"Madaniyah"),(50,"Qaf",45,"Makkiyah"),(51,"Adh-Dhariyat",60,"Makkiyah"),
    (52,"At-Tur",49,"Makkiyah"),(53,"An-Najm",62,"Makkiyah"),(54,"Al-Qamar",55,"Makkiyah"),
    (55,"Ar-Rahman",78,"Madaniyah"),(56,"Al-Waqiah",96,"Makkiyah"),(57,"Al-Hadid",29,"Madaniyah"),
    (58,"Al-Mujadilah",22,"Madaniyah"),(59,"Al-Hashr",24,"Madaniyah"),(60,"Al-Mumtahanah",13,"Madaniyah"),
    (61,"As-Saff",14,"Madaniyah"),(62,"Al-Jumuah",11,"Madaniyah"),(63,"Al-Munafiqun",11,"Madaniyah"),
    (64,"At-Taghabun",18,"Madaniyah"),(65,"At-Talaq",12,"Madaniyah"),(66,"At-Tahrim",12,"Madaniyah"),
    (67,"Al-Mulk",30,"Makkiyah"),(68,"Al-Qalam",52,"Makkiyah"),(69,"Al-Haqqah",52,"Makkiyah"),
    (70,"Al-Maarij",44,"Makkiyah"),(71,"Nuh",28,"Makkiyah"),(72,"Al-Jinn",28,"Makkiyah"),
    (73,"Al-Muzzammil",20,"Makkiyah"),(74,"Al-Muddaththir",56,"Makkiyah"),(75,"Al-Qiyamah",40,"Makkiyah"),
    (76,"Al-Insan",31,"Madaniyah"),(77,"Al-Mursalat",50,"Makkiyah"),(78,"An-Naba",40,"Makkiyah"),
    (79,"An-Naziat",46,"Makkiyah"),(80,"Abasa",42,"Makkiyah"),(81,"At-Takwir",29,"Makkiyah"),
    (82,"Al-Infitar",19,"Makkiyah"),(83,"Al-Mutaffifin",36,"Makkiyah"),(84,"Al-Inshiqaq",25,"Makkiyah"),
    (85,"Al-Buruj",22,"Makkiyah"),(86,"At-Tariq",17,"Makkiyah"),(87,"Al-Ala",19,"Makkiyah"),
    (88,"Al-Ghashiyah",26,"Makkiyah"),(89,"Al-Fajr",30,"Makkiyah"),(90,"Al-Balad",20,"Makkiyah"),
    (91,"Ash-Shams",15,"Makkiyah"),(92,"Al-Layl",21,"Makkiyah"),(93,"Ad-Duhaa",11,"Makkiyah"),
    (94,"Ash-Sharh",8,"Makkiyah"),(95,"At-Tin",8,"Makkiyah"),(96,"Al-Alaq",19,"Makkiyah"),
    (97,"Al-Qadr",5,"Makkiyah"),(98,"Al-Bayyinah",8,"Madaniyah"),(99,"Az-Zalzalah",8,"Madaniyah"),
    (100,"Al-Adiyat",11,"Makkiyah"),(101,"Al-Qariah",11,"Makkiyah"),(102,"At-Takathur",8,"Makkiyah"),
    (103,"Al-Asr",3,"Makkiyah"),(104,"Al-Humazah",9,"Makkiyah"),(105,"Al-Fil",5,"Makkiyah"),
    (106,"Quraysh",4,"Makkiyah"),(107,"Al-Maun",7,"Makkiyah"),(108,"Al-Kawthar",3,"Makkiyah"),
    (109,"Al-Kafirun",6,"Makkiyah"),(110,"An-Nasr",3,"Madaniyah"),(111,"Al-Masad",5,"Makkiyah"),
    (112,"Al-Ikhlas",4,"Makkiyah"),(113,"Al-Falaq",5,"Makkiyah"),(114,"An-Nas",6,"Makkiyah"),
]
SURAH_AR = {1:"الفاتحة",2:"البقرة",3:"آل عمران",4:"النساء",5:"المائدة",6:"الأنعام",7:"الأعراف",8:"الأنفال",9:"التوبة",10:"يونس",11:"هود",12:"يوسف",13:"الرعد",14:"إبراهيم",15:"الحجر",16:"النحل",17:"الإسراء",18:"الكهف",19:"مريم",20:"طه",21:"الأنبياء",22:"الحج",23:"المؤمنون",24:"النور",25:"الفرقان",26:"الشعراء",27:"النمل",28:"القصص",29:"العنكبوت",30:"الروم",31:"لقمان",32:"السجدة",33:"الأحزاب",34:"سبأ",35:"فاطر",36:"يس",37:"الصافات",38:"ص",39:"الزمر",40:"غافر",41:"فصلت",42:"الشورى",43:"الزخرف",44:"الدخان",45:"الجاثية",46:"الأحقاف",47:"محمد",48:"الفتح",49:"الحجرات",50:"ق",51:"الذاريات",52:"الطور",53:"النجم",54:"القمر",55:"الرحمن",56:"الواقعة",57:"الحديد",58:"المجادلة",59:"الحشر",60:"الممتحنة",61:"الصف",62:"الجمعة",63:"المنافقون",64:"التغابن",65:"الطلاق",66:"التحريم",67:"الملك",68:"القلم",69:"الحاقة",70:"المعارج",71:"نوح",72:"الجن",73:"المزمل",74:"المدثر",75:"القيامة",76:"الإنسان",77:"المرسلات",78:"النبأ",79:"النازعات",80:"عبس",81:"التكوير",82:"الانفطار",83:"المطففين",84:"الانشقاق",85:"البروج",86:"الطارق",87:"الأعلى",88:"الغاشية",89:"الفجر",90:"البلد",91:"الشمس",92:"الليل",93:"الضحى",94:"الشرح",95:"التين",96:"العلق",97:"القدر",98:"البينة",99:"الزلزلة",100:"العاديات",101:"القارعة",102:"التكاثر",103:"العصر",104:"الهمزة",105:"الفيل",106:"قريش",107:"الماعون",108:"الكوثر",109:"الكافرون",110:"النصر",111:"المسد",112:"الإخلاص",113:"الفلق",114:"الناس"}

RECITERS = {
    "alafasy": {"name_ar": "مشاري راشد العفاسي", "name_en": "Mishary Rashid Alafasy", "base_url": "https://download.quranicaudio.com/quran/mishaari_raashid_al_3afaasee"},
    "basit": {"name_ar": "عبدالباسط عبدالصمد", "name_en": "Abdul Basit", "base_url": "https://download.quranicaudio.com/quran/abdul_basit_murattal"},
    "minshawi": {"name_ar": "محمد صديق المنشاوي", "name_en": "Mohamed Siddiq al-Minshawi", "base_url": "https://download.quranicaudio.com/quran/muhammad_siddeeq_al-minshaawee"},
    "ajmi": {"name_ar": "أحمد العجمي", "name_en": "Ahmed ibn Ali al-Ajamy", "base_url": "https://download.quranicaudio.com/quran/ahmed_ibn_3ali_al-3ajamy"},
    "yasser": {"name_ar": "ياسر الدوسري", "name_en": "Yasser Ad-Dosari", "base_url": "https://download.quranicaudio.com/quran/yasser_ad-dussary"},
    "muaiqly": {"name_ar": "ماهر المعيقلي", "name_en": "Maher al-Mu'aiqly", "base_url": "https://download.quranicaudio.com/quran/maher_almu3aiqly/year1440"},
    "shuraim": {"name_ar": "سعود الشريم", "name_en": "Saood ash-Shuraym", "base_url": "https://download.quranicaudio.com/quran/sa3ood_al-shuraym"},
    "ayyub": {"name_ar": "محمد أيوب", "name_en": "Muhammad Ayyoub", "base_url": "https://download.quranicaudio.com/quran/muhammad_ayyoob_hq"},
    "shatri": {"name_ar": "أبو بكر الشاطري", "name_en": "Abu Bakr Al Shatri", "base_url": "https://download.quranicaudio.com/quran/abu_bakr_ash-shatri"},
    "ali_jaber": {"name_ar": "علي جابر", "name_en": "Ali Jaber", "base_url": "https://download.quranicaudio.com/quran/ali_jaber"},
    "fares_abbad": {"name_ar": "فارس عباد", "name_en": "Fares Abbad", "base_url": "https://download.quranicaudio.com/quran/fares_abbad"},
    "abdulrahman_ossi": {"name_ar": "عبدالرحمن العوسي", "name_en": "Abdulrahman Al Ossi", "base_url": "https://download.quranicaudio.com/quran/abdul_rahman_al_ossi"},
    "omar_qazabri": {"name_ar": "عمر القزابري", "name_en": "Omar Al Qazabri", "base_url": "https://download.quranicaudio.com/quran/omar_al_qazabri"},
    "luhaidan": {"name_ar": "محمد اللحيدان", "name_en": "Mohammed Al Luhaidan", "base_url": "https://download.quranicaudio.com/quran/muhammad_al_luhaidan"},
    "matrood": {"name_ar": "عبدالله المطرود", "name_en": "Abdullah Al Matrood", "base_url": "https://download.quranicaudio.com/quran/abdullah_al_matrood"},
    "hawashi": {"name_ar": "أحمد الحواشي", "name_en": "Ahmad Al Hawashi", "base_url": "https://download.quranicaudio.com/quran/ahmad_al_hawashi"},
    "rifai": {"name_ar": "هاني الرفاعي", "name_en": "Hani ar-Rifai", "base_url": "https://download.quranicaudio.com/quran/rifai"},
    "nasser": {"name_ar": "ناصر القطامي", "name_en": "Nasser al-Qatami", "base_url": "https://download.quranicaudio.com/quran/nasser_bin_ali_alqatami"},
    "sudais": {"name_ar": "عبدالرحمن السديس", "name_en": "Abdurrahman as-Sudais", "base_url": "https://download.quranicaudio.com/quran/abdurrahmaan_as-sudays"},
    "husary": {"name_ar": "محمود خليل الحصري", "name_en": "Mahmoud Khalil al-Hussary", "base_url": "https://download.quranicaudio.com/quran/mahmood_khaleel_al-husaree_iza3a"},
    "ghamdi": {"name_ar": "سعد الغامدي", "name_en": "Saad al-Ghamdi", "base_url": "https://download.quranicaudio.com/quran/sa3d_al-ghaamidi/complete"},
    "hudhaify": {"name_ar": "علي الحذيفي", "name_en": "Ali al-Hudhaify", "base_url": "https://download.quranicaudio.com/quran/huthayfi"},
    "basfar": {"name_ar": "عبدالله بصر", "name_en": "Abdullah Ibn Ali Basfar", "base_url": "https://download.quranicaudio.com/quran/abdullaah_basfar"},
    "jibreel": {"name_ar": "محمد جبريل", "name_en": "Muhammad Jibreel", "base_url": "https://download.quranicaudio.com/quran/muhammad_jibreel/complete"},
    "tablaway": {"name_ar": "محمد الطلاوي", "name_en": "Mohammad al-Tablaway", "base_url": "https://download.quranicaudio.com/quran/mohammad_altablawi"},
    "juhany": {"name_ar": "عبدالله الجهني", "name_en": "Abdullaah al-Juhany", "base_url": "https://download.quranicaudio.com/quran/abdullaah_3awwaad_al-juhaynee"},
    "banna": {"name_ar": "محمود علي البنا", "name_en": "Mahmoud Ali al-Banna", "base_url": "https://download.quranicaudio.com/quran/mahmood_ali_albana"},
    "qasim": {"name_ar": "عبدالمحسن القاسم", "name_en": "Muhsin al-Qasim", "base_url": "https://download.quranicaudio.com/quran/abdul_muhsin_alqasim"},
}

# --- Quran additional info: سبب النزول وتفسير مختصر ---
QURAN_REASONS = {
    1: "سورة الفاتحة مكية، سميت بأم القرآن، نزلت لتعليم المسلمين حمد الله والاستعانة به. هي ركن الصلاة.",
    2: "سورة البقرة مدنية، أول سورة نزلت بالمدينة، تعالج أحكام التشريع والعبادات وتقص قصص بني إسرائيل.",
    3: "آل عمران مدنية، نزلت بعد غزوة بدر، تثبت عقيدة التوحيد وترد على النصارى.",
    36: "يس مكية، قلب القرآن، نزلت لتثبيت النبي وتأكيد الرسالة والبعث.",
    18: "الكهف مكية، نزلت ردا على أسئلة المشركين عن أصحاب الكهف وذي القرنين.",
    55: "الرحمن مدنية، نزلت لتبيان نعم الله وتذكير الجن والإنس.",
    67: "الملك مكية، نزلت لتأكيد عظمة الله وقدرته والترغيب في التفكر.",
    112: "الإخلاص مكية، تعدل ثلث القرآن، نزلت ردا على من سأل عن صفة الله.",
}
QURAN_TAFSIR = {
    1: "تفسير الفاتحة: حمد لله وثناء عليه، إقرار بربوبيته، طلب الهداية للصراط المستقيم. ابن كثير",
    2: "تفسير البقرة: أحكام الصلاة والصيام والحج، قصص الأنبياء، آيات الربا والدين. القرطبي",
    36: "يس: تأكيد نبوة محمد، قصص القرون، إحياء الموتى دليل البعث. الطبري",
    18: "الكهف: عصمة من الفتن الأربع (الدين، المال، العلم، السلطة). السعدي",
}

# ترجمات مختارة (EN/FR) - سورة الفاتحة والاخلاص كمثال، الباقي يجلب من API
QURAN_TRANSLATIONS = {
    1: {
        1: {"ar": "بسم الله الرحمن الرحيم", "en": "In the name of Allah, the Entirely Merciful, the Especially Merciful.", "fr": "Au nom d'Allah, le Tout Miséricordieux, le Très Miséricordieux.", "ber": "Tasuqilt s tmazight."},
        2: {"ar": "الحمد لله رب العالمين", "en": "All praise is due to Allah, Lord of the worlds.", "fr": "Louange à Allah, Seigneur de l'univers.", "ber": "Tasuqilt s tmazight."},
        3: {"ar": "الرحمن الرحيم", "en": "The Entirely Merciful, the Especially Merciful.", "fr": "Le Tout Miséricordieux, le Très Miséricordieux.", "ber": "Tasuqilt s tmazight."},
        4: {"ar": "مالك يوم الدين", "en": "Sovereign of the Day of Recompense.", "fr": "Maître du Jour de la rétribution.", "ber": "Tasuqilt s tmazight."},
        5: {"ar": "إياك نعبد وإياك نستعين", "en": "It is You we worship and You we ask for help.", "fr": "C'est Toi seul que nous adorons, et c'est Toi seul dont nous implorons secours.", "ber": "Tasuqilt s tmazight."},
        6: {"ar": "اهدنا الصراط المستقيم", "en": "Guide us to the straight path.", "fr": "Guide-nous dans le droit chemin.", "ber": "Tasuqilt s tmazight."},
        7: {"ar": "صراط الذين أنعمت عليهم غير المغضوب عليهم ولا الضالين", "en": "The path of those upon whom You have bestowed favor, not of those who have evoked Your anger or of those who are astray.", "fr": "Le chemin de ceux que Tu as comblés de faveurs, non pas de ceux qui ont encouru Ta colère, ni des égarés.", "ber": "Tasuqilt s tmazight."},
    },
    112: {
        1: {"ar": "قل هو الله أحد", "en": "Say, He is Allah, [who is] One.", "fr": "Dis: Il est Allah, Unique.", "ber": "Tasuqilt s tmazight."},
        2: {"ar": "الله الصمد", "en": "Allah, the Eternal Refuge.", "fr": "Allah, Le Seul à être imploré pour ce que nous désirons.", "ber": "Tasuqilt s tmazight."},
        3: {"ar": "لم يلد ولم يولد", "en": "He neither begets nor is born.", "fr": "Il n'a jamais engendré, n'a pas été engendré non plus.", "ber": "Tasuqilt s tmazight."},
        4: {"ar": "ولم يكن له كفوا أحد", "en": "Nor is there to Him any equivalent.", "fr": "Et nul n'est égal à Lui.", "ber": "Tasuqilt s tmazight."},
    }
}

# --- Hadith Sahih (متفق عليه) ---
HADITH_DB = [
    {"id": 1, "collection": "البخاري ومسلم", "narrator": "عمر بن الخطاب", "text_ar": "إنما الأعمال بالنيات، وإنما لكل امرئ ما نوى، فمن كانت هجرته إلى الله ورسوله فهجرته إلى الله ورسوله، ومن كانت هجرته لدنيا يصيبها أو امرأة ينكحها فهجرته إلى ما هاجر إليه.", "text_en": "Actions are judged by intentions...", "text_fr": "Les actes ne valent que par les intentions...", "grade": "متفق عليه", "explanation_ar": "هذا الحديث أصل عظيم في الدين، يبين أن النية هي مدار الأعمال صحة وفسادا. شرح النووي وابن عثيمين.", "explanation_en": "Foundation of Islam: intention determines reward.", "explanation_fr": "Fondement: l'intention détermine la récompense.", "text_ber": "Hadit s tmazight - ⴰⴷⵍⵉⵙ ⵏ ⵍⵃⴰⴷⵉⵜ.", "explanation_ber": "Asegzi s tmazight - ⴰⵙⴻⴳⵣⵉ.", "topic": "النية"},
    {"id": 2, "collection": "البخاري", "narrator": "أبو هريرة", "text_ar": "من صام رمضان إيمانا واحتسابا غفر له ما تقدم من ذنبه.", "text_en": "Whoever fasts Ramadan with faith and seeking reward, his past sins are forgiven.", "text_fr": "Quiconque jeûne Ramadan avec foi...", "grade": "صحيح", "explanation_ar": "يبين فضل الصيام الخالص لله وشرط الإيمان والاحتساب. فتح الباري.", "explanation_en": "Virtue of sincere fasting.", "explanation_fr": "Vertu du jeûne sincère.", "text_ber": "Hadit s tmazight - ⴰⴷⵍⵉⵙ ⵏ ⵍⵃⴰⴷⵉⵜ.", "explanation_ber": "Asegzi s tmazight - ⴰⵙⴻⴳⵣⵉ.", "topic": "الصيام"},
    {"id": 3, "collection": "مسلم", "narrator": "تميم الداري", "text_ar": "الدين النصيحة، قلنا لمن؟ قال: لله ولكتابه ولرسوله ولأئمة المسلمين وعامتهم.", "text_en": "Religion is sincere advice...", "text_fr": "La religion est le bon conseil...", "grade": "صحيح", "explanation_ar": "النصيحة عماد الدين: إخلاص لله واتباع للكتاب والسنة ونصح للحكام والعامة. شرح مسلم.", "explanation_en": "Sincere advice is religion.", "explanation_fr": "Le bon conseil est la religion.", "text_ber": "Hadit s tmazight - ⴰⴷⵍⵉⵙ ⵏ ⵍⵃⴰⴷⵉⵜ.", "explanation_ber": "Asegzi s tmazight - ⴰⵙⴻⴳⵣⵉ.", "topic": "النصيحة"},
    {"id": 4, "collection": "البخاري", "narrator": "عائشة", "text_ar": "من أحدث في أمرنا هذا ما ليس منه فهو رد.", "text_en": "Whoever innovates in our matter what is not part of it will have it rejected.", "text_fr": "Quiconque innove dans notre affaire...", "grade": "متفق عليه", "explanation_ar": "أصل في رد البدع، كل عبادة لا أصل لها في الشرع مردودة. ابن رجب.", "explanation_en": "Principle of rejecting innovations.", "explanation_fr": "Principe du rejet des innovations.", "text_ber": "Hadit s tmazight - ⴰⴷⵍⵉⵙ ⵏ ⵍⵃⴰⴷⵉⵜ.", "explanation_ber": "Asegzi s tmazight - ⴰⵙⴻⴳⵣⵉ.", "topic": "البدعة"},
    {"id": 5, "collection": "مسلم", "narrator": "أبو هريرة", "text_ar": "لا يؤمن أحدكم حتى يحب لأخيه ما يحب لنفسه.", "text_en": "None of you believes until he loves for his brother what he loves for himself.", "text_fr": "Aucun de vous ne croira jusqu'à aimer pour son frère...", "grade": "متفق عليه", "explanation_ar": "كمال الإيمان في الأخوة الإيمانية والإيثار. شرح النووي.", "explanation_en": "Perfection of faith is brotherhood.", "explanation_fr": "Perfection de la foi.", "text_ber": "Hadit s tmazight - ⴰⴷⵍⵉⵙ ⵏ ⵍⵃⴰⴷⵉⵜ.", "explanation_ber": "Asegzi s tmazight - ⴰⵙⴻⴳⵣⵉ.", "topic": "الإيمان"},
    {"id": 6, "collection": "البخاري", "narrator": "عبدالله بن عمر", "text_ar": "بني الإسلام على خمس: شهادة أن لا إله إلا الله وأن محمدا رسول الله، وإقام الصلاة، وإيتاء الزكاة، وصوم رمضان، وحج البيت.", "text_en": "Islam is built on five pillars...", "text_fr": "L'Islam est bâti sur cinq piliers...", "grade": "متفق عليه", "explanation_ar": "أركان الإسلام الخمسة، أساس الدين. شرح ابن بطال.", "explanation_en": "Five pillars of Islam.", "explanation_fr": "Cinq piliers.", "text_ber": "Hadit s tmazight - ⴰⴷⵍⵉⵙ ⵏ ⵍⵃⴰⴷⵉⵜ.", "explanation_ber": "Asegzi s tmazight - ⴰⵙⴻⴳⵣⵉ.", "topic": "الأركان"},
    {"id": 7, "collection": "البخاري", "narrator": "أبو هريرة", "text_ar": "كلمتان خفيفتان على اللسان ثقيلتان في الميزان حبيبتان إلى الرحمن: سبحان الله وبحمده سبحان الله العظيم.", "text_en": "Two words light on tongue heavy on scale...", "text_fr": "Deux paroles légères...", "grade": "متفق عليه", "explanation_ar": "فضل الذكر ويسر العبادة وعظم الأجر. ابن حجر.", "explanation_en": "Virtue of remembrance.", "explanation_fr": "Vertu du dhikr.", "text_ber": "Hadit s tmazight - ⴰⴷⵍⵉⵙ ⵏ ⵍⵃⴰⴷⵉⵜ.", "explanation_ber": "Asegzi s tmazight - ⴰⵙⴻⴳⵣⵉ.", "topic": "الذكر"},
    {"id": 8, "collection": "مسلم", "narrator": "أبو ذر", "text_ar": "اتق الله حيثما كنت وأتبع السيئة الحسنة تمحها وخالق الناس بخلق حسن.", "text_en": "Fear Allah wherever you are...", "text_fr": "Crains Allah où que tu sois...", "grade": "حسن صحيح", "explanation_ar": "جامع للتقوى ومداراة الناس. الترمذي.", "explanation_en": "Fear Allah and good character.", "explanation_fr": "Crainte d'Allah.", "text_ber": "Hadit s tmazight - ⴰⴷⵍⵉⵙ ⵏ ⵍⵃⴰⴷⵉⵜ.", "explanation_ber": "Asegzi s tmazight - ⴰⵙⴻⴳⵣⵉ.", "topic": "التقوى"},
    {"id": 9, "collection": "البخاري", "narrator": "سهل بن سعد", "text_ar": "إنما الأعمال بخواتيمها.", "text_en": "Actions are judged by their endings.", "text_fr": "Les actes sont jugés par leur fin.", "grade": "صحيح", "explanation_ar": "العبرة بالخاتمة وحسن الختام. ابن حجر.", "explanation_en": "Consider endings.", "explanation_fr": "La fin compte.", "text_ber": "Hadit s tmazight - ⴰⴷⵍⵉⵙ ⵏ ⵍⵃⴰⴷⵉⵜ.", "explanation_ber": "Asegzi s tmazight - ⴰⵙⴻⴳⵣⵉ.", "topic": "الخاتمة"},
    {"id": 10, "collection": "البخاري", "narrator": "أنس", "text_ar": "يسروا ولا تعسروا وبشروا ولا تنفروا.", "text_en": "Make easy, do not make difficult, give glad tidings.", "text_fr": "Facilitez et ne compliquez pas...", "grade": "صحيح", "explanation_ar": "منهج الدعوة والتيسير في الشريعة. فتح الباري.", "explanation_en": "Ease in religion.", "explanation_fr": "Facilité.", "text_ber": "Hadit s tmazight - ⴰⴷⵍⵉⵙ ⵏ ⵍⵃⴰⴷⵉⵜ.", "explanation_ber": "Asegzi s tmazight - ⴰⵙⴻⴳⵣⵉ.", "topic": "التيسير"},
    {"id": 11, "collection": "البخاري ومسلم", "narrator": "عمر بن الخطاب", "text_ar": "لا ضرر ولا ضرار.", "text_en": "No harm and no reciprocating harm.", "text_fr": "Pas de tort ni de préjudice.", "grade": "متفق عليه", "explanation_ar": "قاعدة فقهية كبرى. ابن رجب.", "explanation_en": "No harm principle.", "explanation_fr": "Pas de préjudice.", "text_ber": "Hadit s tmazight - ⴰⴷⵍⵉⵙ ⵏ ⵍⵃⴰⴷⵉⵜ.", "explanation_ber": "Asegzi s tmazight - ⴰⵙⴻⴳⵣⵉ.", "topic": "القواعد الفقهية"},
    {"id": 12, "collection": "مسلم", "narrator": "أبو هريرة", "text_ar": "من سلك طريقا يلتمس فيه علما سهل الله له به طريقا إلى الجنة.", "text_en": "Whoever takes a path seeking knowledge, Allah eases for him a path to Paradise.", "text_fr": "Quiconque emprunte un chemin à la recherche du savoir...", "grade": "صحيح", "explanation_ar": "فضل طلب العلم الشرعي والدنيوي النافع. النووي.", "explanation_en": "Virtue of seeking knowledge.", "explanation_fr": "Vertu du savoir.", "text_ber": "Hadit s tmazight - ⴰⴷⵍⵉⵙ ⵏ ⵍⵃⴰⴷⵉⵜ.", "explanation_ber": "Asegzi s tmazight - ⴰⵙⴻⴳⵣⵉ.", "topic": "العلم"},
]

SOFTWARE_DB = [
    {"id":"freecad","name":"FreeCAD","category":"architecture","type":"free","description_en":"Free parametric 3D CAD modeler","description_ar":"برنامج CAD ثلاثي الأبعاد مجاني","website":"https://www.freecad.org","download_url":"https://www.freecad.org/downloads.php","icon":"\U0001f3d7\ufe0f","alternatives_to":["ArchiCAD","Revit","AutoCAD"],"platforms":["Windows","Mac","Linux"],"size":"~400 MB","version":"1.0"},
    {"id":"librecad","name":"LibreCAD","category":"architecture","type":"free","description_en":"Free 2D CAD application","description_ar":"تطبيق CAD ثنائي الأبعاد مجاني","website":"https://librecad.org","download_url":"https://librecad.org/www/main/download.html","icon":"\U0001f4d0","alternatives_to":["AutoCAD"],"platforms":["Windows","Mac","Linux"],"size":"~50 MB","version":"2.2"},
    {"id":"twinmotion","name":"Twinmotion","category":"render","type":"free_limited","description_en":"Real-time visualization (free non-commercial)","description_ar":"أداة تصوير فوري (مجاني للاستخدام غير التجاري)","website":"https://www.twinmotion.com","download_url":"https://www.twinmotion.com/en/download","icon":"\U0001f3e0","alternatives_to":["Lumion","V-Ray"],"platforms":["Windows","Mac"],"size":"~2 GB","version":"2024.1"},
    {"id":"blender","name":"Blender","category":"3d","type":"free","description_en":"Free open-source 3D creation suite","description_ar":"مجموعة إبداع ثلاثية الأبعاد مجانية ومفتوحة المصدر","website":"https://www.blender.org","download_url":"https://www.blender.org/download/","icon":"\U0001f52c","alternatives_to":["Maya","3ds Max","Cinema 4D"],"platforms":["Windows","Mac","Linux"],"size":"~350 MB","version":"4.2"},
    {"id":"gimp","name":"GIMP","category":"design","type":"free","description_en":"GNU Image Manipulation Program","description_ar":"برنامج معالجة الصور من جنو","website":"https://www.gimp.org","download_url":"https://www.gimp.org/downloads/","icon":"\U0001f3a8","alternatives_to":["Photoshop","Affinity Photo"],"platforms":["Windows","Mac","Linux"],"size":"~300 MB","version":"2.10"},
    {"id":"inkscape","name":"Inkscape","category":"design","type":"free","description_en":"Free vector graphics editor","description_ar":"محرر رسومات مجانية","website":"https://inkscape.org","download_url":"https://inkscape.org/release/","icon":"\U0001f58c\ufe0f","alternatives_to":["Illustrator","CorelDRAW"],"platforms":["Windows","Mac","Linux"],"size":"~120 MB","version":"1.3"},
    {"id":"krita","name":"Krita","category":"design","type":"free","description_en":"Free painting program","description_ar":"برنامج رسم مجاني","website":"https://krita.org","download_url":"https://krita.org/en/download/","icon":"\U0001f3a8","alternatives_to":["Photoshop","Clip Studio Paint"],"platforms":["Windows","Mac","Linux"],"size":"~250 MB","version":"5.2"},
    {"id":"scribus","name":"Scribus","category":"design","type":"free","description_en":"Free desktop publishing","description_ar":"نشر مكتبي مجاني","website":"https://www.scribus.net","download_url":"https://www.scribus.net/download/","icon":"\U0001f4d6","alternatives_to":["InDesign","Publisher"],"platforms":["Windows","Mac","Linux"],"size":"~200 MB","version":"1.6"},
    {"id":"libreoffice","name":"LibreOffice","category":"office","type":"free","description_en":"Free office suite","description_ar":"مجموعة مكتبية مجانية","website":"https://www.libreoffice.org","download_url":"https://www.libreoffice.org/download/download-libreoffice/","icon":"\U0001f4c4","alternatives_to":["Microsoft Office","WPS Office"],"platforms":["Windows","Mac","Linux"],"size":"~350 MB","version":"24.8"},
    {"id":"obs","name":"OBS Studio","category":"video","type":"free","description_en":"Free video recording and streaming","description_ar":"تسجيل وبث فيديو مجاني","website":"https://obsproject.com","download_url":"https://obsproject.com/download","icon":"\U0001f3ac","alternatives_to":["Camtasia","ScreenFlow"],"platforms":["Windows","Mac","Linux"],"size":"~120 MB","version":"30.2"},
    {"id":"kdenlive","name":"Kdenlive","category":"video","type":"free","description_en":"Free non-linear video editor","description_ar":"محرر فيديو غير خطي مجاني","website":"https://kdenlive.org","download_url":"https://kdenlive.org/en/download/","icon":"\U0001f3ac","alternatives_to":["Premiere Pro","Final Cut Pro"],"platforms":["Windows","Mac","Linux"],"size":"~200 MB","version":"24.05"},
    {"id":"shotcut","name":"Shotcut","category":"video","type":"free","description_en":"Free video editor","description_ar":"محرر فيديو مجاني","website":"https://shotcut.org","download_url":"https://shotcut.org/download/","icon":"\U0001f3ac","alternatives_to":["Premiere Pro"],"platforms":["Windows","Mac","Linux"],"size":"~150 MB","version":"24.06"},
    {"id":"davinci_resolve","name":"DaVinci Resolve","category":"video","type":"free","description_en":"Professional video editor (free version)","description_ar":"محرر فيديو احترافي (نسخة مجانية)","website":"https://www.blackmagicdesign.com","download_url":"https://www.blackmagicdesign.com/products/davinciresolve","icon":"\U0001f3ac","alternatives_to":["Premiere Pro","Final Cut Pro"],"platforms":["Windows","Mac","Linux"],"size":"~2.5 GB","version":"19.0"},
    {"id":"audacity","name":"Audacity","category":"audio","type":"free","description_en":"Free audio editor","description_ar":"محرر صوت مجاني","website":"https://www.audacityteam.org","download_url":"https://www.audacityteam.org/download/","icon":"\U0001f3b5","alternatives_to":["Adobe Audition","FL Studio"],"platforms":["Windows","Mac","Linux"],"size":"~70 MB","version":"3.6"},
    {"id":"lmms","name":"LMMS","category":"audio","type":"free","description_en":"Free music production","description_ar":"إنتاج موسيقي مجاني","website":"https://lmms.io","download_url":"https://lmms.io/download","icon":"\U0001f3b5","alternatives_to":["FL Studio","Ableton Live"],"platforms":["Windows","Mac","Linux"],"size":"~100 MB","version":"1.2"},
    {"id":"ardour","name":"Ardour","category":"audio","type":"free","description_en":"Free digital audio workstation","description_ar":"محطة صوت رقمي مجانية","website":"https://ardour.org","download_url":"https://ardour.org/download.html","icon":"\U0001f3b5","alternatives_to":["Logic Pro","Pro Tools"],"platforms":["Windows","Mac","Linux"],"size":"~150 MB","version":"8.6"},
    {"id":"handbrake","name":"HandBrake","category":"video","type":"free","description_en":"Free video transcoder","description_ar":"محول فيديو مجاني","website":"https://handbrake.fr","download_url":"https://handbrake.fr/download.php","icon":"\U0001f504","alternatives_to":["Any Video Converter"],"platforms":["Windows","Mac","Linux"],"size":"~25 MB","version":"1.8"},
    {"id":"vlc","name":"VLC Media Player","category":"video","type":"free","description_en":"Free media player","description_ar":"مشغل وسائط مجاني","website":"https://www.videolan.org","download_url":"https://www.videolan.org/vlc/","icon":"\U0001f3ac","alternatives_to":["KMPlayer"],"platforms":["Windows","Mac","Linux"],"size":"~50 MB","version":"3.0.21"},
    {"id":"vscode","name":"Visual Studio Code","category":"programming","type":"free","description_en":"Free code editor by Microsoft","description_ar":"محرر أكواد مجاني من مايكروسوفت","website":"https://code.visualstudio.com","download_url":"https://code.visualstudio.com/download","icon":"\U0001f4bb","alternatives_to":["Sublime Text","WebStorm"],"platforms":["Windows","Mac","Linux"],"size":"~100 MB","version":"1.92"},
    {"id":"openscad","name":"OpenSCAD","category":"3d","type":"free","description_en":"Free script-based 3D CAD","description_ar":"CAD ثلاثي الأبعاد قائم على السكربتات","website":"https://openscad.org","download_url":"https://openscad.org/downloads.html","icon":"\U0001f4d0","alternatives_to":["FreeCAD"],"platforms":["Windows","Mac","Linux"],"size":"~50 MB","version":"2024"},
    {"id":"kerkythea","name":"Kerkythea","category":"render","type":"free","description_en":"Free rendering engine","description_ar":"محرك تطعيم مجاني","website":"http://www.kerkythea.net","download_url":"http://www.kerkythea.net/Downloads","icon":"\U0001f3d7\ufe0f","alternatives_to":["V-Ray","Lumion"],"platforms":["Windows","Mac","Linux"],"size":"~200 MB","version":"2.0"},
    {"id":"7zip","name":"7-Zip","category":"utility","type":"free","description_en":"Free file archiver","description_ar":"أداة ضغط ملفات مجانية","website":"https://www.7-zip.org","download_url":"https://www.7-zip.org/download.html","icon":"\U0001f4e6","alternatives_to":["WinRAR","WinZip"],"platforms":["Windows"],"size":"~2 MB","version":"24.05"},
    {"id":"notepadpp","name":"Notepad++","category":"programming","type":"free","description_en":"Free source code editor","description_ar":"محرر أكواد مجاني","website":"https://notepad-plus-plus.org","download_url":"https://notepad-plus-plus.org/downloads/","icon":"\U0001f4dd","alternatives_to":["Sublime Text"],"platforms":["Windows"],"size":"~5 MB","version":"8.6"},
    {"id":"autocad","name":"AutoCAD","category":"architecture","type":"paid","description_en":"Industry-leading CAD software","description_ar":"برنامج CAD رائد في الصناعة","website":"https://www.autodesk.com","download_url":"https://www.autodesk.com/products/autocad/free-trial","icon":"\U0001f4d0","alternatives_to":["FreeCAD","LibreCAD"],"platforms":["Windows","Mac"],"price":"$1,865/yr","version":"2025"},
    {"id":"revit","name":"Revit","category":"architecture","type":"paid","description_en":"BIM software for architecture","description_ar":"برنامج نمذجة معلومات البناء","website":"https://www.autodesk.com","download_url":"https://www.autodesk.com/products/revit/free-trial","icon":"\U0001f3d7\ufe0f","alternatives_to":["FreeCAD","ArchiCAD"],"platforms":["Windows"],"price":"$2,545/yr","version":"2025"},
    {"id":"archicad","name":"ArchiCAD","category":"architecture","type":"paid","description_en":"BIM software","description_ar":"برنامج معماري ثلاثي الأبعاد","website":"https://graphisoft.com","download_url":"https://graphisoft.com/solutions/archicad/trial","icon":"\U0001f3d7\ufe0f","alternatives_to":["Revit","FreeCAD"],"platforms":["Windows","Mac"],"price":"$2,000+/yr","version":"28"},
    {"id":"sketchup","name":"SketchUp","category":"3d","type":"paid","description_en":"3D modeling software","description_ar":"برنامج نمذجة ثلاثية الأبعاد","website":"https://www.sketchup.com","download_url":"https://www.sketchup.com/product/try-sketchup","icon":"\U0001f4d0","alternatives_to":["Blender","FreeCAD"],"platforms":["Windows","Mac"],"price":"$349/yr","version":"2024"},
    {"id":"maya","name":"Maya","category":"3d","type":"paid","description_en":"Professional 3D animation","description_ar":"رسوم متحركة ثلاثية الأبعاد احترافية","website":"https://www.autodesk.com","download_url":"https://www.autodesk.com/products/maya/free-trial","icon":"\U0001f52c","alternatives_to":["Blender","Cinema 4D"],"platforms":["Windows","Mac","Linux"],"price":"$1,875/yr","version":"2025"},
    {"id":"3dsmax","name":"3ds Max","category":"3d","type":"paid","description_en":"Professional 3D modeling and animation","description_ar":"نمذجة ورسوم متحركة ثلاثية الأبعاد احترافية","website":"https://www.autodesk.com","download_url":"https://www.autodesk.com/products/3ds-max/free-trial","icon":"\U0001f52c","alternatives_to":["Blender","Maya"],"platforms":["Windows"],"price":"$1,875/yr","version":"2025"},
    {"id":"cinema4d","name":"Cinema 4D","category":"3d","type":"paid","description_en":"Professional 3D graphics","description_ar":"رسومات ثلاثية الأبعاد احترافية","website":"https://www.maxon.net","download_url":"https://www.maxon.net/cinema-4d","icon":"\U0001f52c","alternatives_to":["Blender","Maya"],"platforms":["Windows","Mac"],"price":"$719/yr","version":"2024"},
    {"id":"houdini","name":"Houdini","category":"3d","type":"paid","description_en":"VFX and 3D animation software","description_ar":"برنامج مؤثرات بصرية ورسوم متحركة","website":"https://www.sidefx.com","download_url":"https://www.sidefx.com/download/","icon":"\U0001f52c","alternatives_to":["Blender","Maya"],"platforms":["Windows","Mac","Linux"],"price":"$4,495","version":"20.5"},
    {"id":"photoshop","name":"Adobe Photoshop","category":"design","type":"paid","description_en":"Industry-standard image editor","description_ar":"محرر الصور القياسي في الصناعة","website":"https://www.adobe.com","download_url":"https://www.adobe.com/products/photoshop/free-trial.html","icon":"\U0001f3a8","alternatives_to":["GIMP","Krita"],"platforms":["Windows","Mac"],"price":"$22.99/mo","version":"2025"},
    {"id":"illustrator","name":"Adobe Illustrator","category":"design","type":"paid","description_en":"Vector graphics editor","description_ar":"محرر رسومات متجهية","website":"https://www.adobe.com","download_url":"https://www.adobe.com/products/illustrator/free-trial.html","icon":"\U0001f58c\ufe0f","alternatives_to":["Inkscape"],"platforms":["Windows","Mac"],"price":"$22.99/mo","version":"2025"},
    {"id":"coreldraw","name":"CorelDRAW","category":"design","type":"paid","description_en":"Vector graphics suite","description_ar":"مجموعة رسومات متجهية","website":"https://www.corel.com","download_url":"https://www.corel.com/en/free-trials/","icon":"\U0001f58c\ufe0f","alternatives_to":["Inkscape","Illustrator"],"platforms":["Windows","Mac"],"price":"$549/yr","version":"2024"},
    {"id":"premiere","name":"Adobe Premiere Pro","category":"video","type":"paid","description_en":"Professional video editor","description_ar":"محرر فيديو احترافي","website":"https://www.adobe.com","download_url":"https://www.adobe.com/products/premiere/free-trial.html","icon":"\U0001f3ac","alternatives_to":["DaVinci Resolve","Final Cut Pro"],"platforms":["Windows","Mac"],"price":"$22.99/mo","version":"2025"},
    {"id":"finalcut","name":"Final Cut Pro","category":"video","type":"paid","description_en":"Professional video editor for Mac","description_ar":"محرر فيديو احترافي للماك","website":"https://www.apple.com","download_url":"https://www.apple.com/final-cut-pro/trial/","icon":"\U0001f3ac","alternatives_to":["DaVinci Resolve","Premiere Pro"],"platforms":["Mac"],"price":"$299.99","version":"10.8"},
    {"id":"vegas","name":"Vegas Pro","category":"video","type":"paid","description_en":"Professional video editing","description_ar":"تحرير فيديو احترافي","website":"https://www.vegascreativesoftware.com","download_url":"https://www.vegascreativesoftware.com/us/vegas-pro/trial/","icon":"\U0001f3ac","alternatives_to":["Premiere Pro","DaVinci Resolve"],"platforms":["Windows"],"price":"$399","version":"22"},
    {"id":"flstudio","name":"FL Studio","category":"audio","type":"paid","description_en":"Music production software","description_ar":"برنامج إنتاج موسيقي","website":"https://www.image-line.com","download_url":"https://www.image-line.com/fl-studio-download/","icon":"\U0001f3b5","alternatives_to":["Ableton Live","LMMS"],"platforms":["Windows","Mac"],"price":"$99-$499","version":"2024"},
    {"id":"ableton","name":"Ableton Live","category":"audio","type":"paid","description_en":"Music production and performance","description_ar":"إنتاج وأداء موسيقي","website":"https://www.ableton.com","download_url":"https://www.ableton.com/en/live/try/","icon":"\U0001f3b5","alternatives_to":["FL Studio","Logic Pro"],"platforms":["Windows","Mac"],"price":"$99-$749","version":"12"},
    {"id":"logicpro","name":"Logic Pro","category":"audio","type":"paid","description_en":"Professional music production for Mac","description_ar":"إنتاج موسيقي احترافي للماك","website":"https://www.apple.com","download_url":"https://www.apple.com/logic-pro/trial/","icon":"\U0001f3b5","alternatives_to":["Ableton Live","FL Studio"],"platforms":["Mac"],"price":"$199.99","version":"11"},
    {"id":"msoffice","name":"Microsoft Office","category":"office","type":"paid","description_en":"Industry-standard office suite","description_ar":"المجموعة المكتبية القياسية","website":"https://www.microsoft.com","download_url":"https://www.microsoft.com/en-us/microsoft-365/try","icon":"\U0001f4c4","alternatives_to":["LibreOffice"],"platforms":["Windows","Mac"],"price":"$69.99/yr","version":"2024"},
    {"id":"intellij","name":"IntelliJ IDEA","category":"programming","type":"paid","description_en":"Professional Java IDE","description_ar":"بيئة تطوير احترافية للجافا","website":"https://www.jetbrains.com","download_url":"https://www.jetbrains.com/idea/download/","icon":"\U0001f4bb","alternatives_to":["VS Code","Eclipse"],"platforms":["Windows","Mac","Linux"],"price":"$149/yr","version":"2024.2"},
    {"id":"sublimetext","name":"Sublime Text","category":"programming","type":"paid","description_en":"Sophisticated text editor","description_ar":"محرر نصوص متطور","website":"https://www.sublimetext.com","download_url":"https://www.sublimetext.com/download","icon":"\U0001f4dd","alternatives_to":["VS Code","Notepad++"],"platforms":["Windows","Mac","Linux"],"price":"$99","version":"4"},
    {"id":"lumion","name":"Lumion","category":"render","type":"paid","description_en":"3D rendering software","description_ar":"برنامج تطعيم ثلاثي الأبعاد","website":"https://lumion.com","download_url":"https://lumion.com/download","icon":"\U0001f3d7\ufe0f","alternatives_to":["Twinmotion","V-Ray"],"platforms":["Windows"],"price":"$1,625/yr","version":"2024"},
    {"id":"vray","name":"V-Ray","category":"render","type":"paid","description_en":"Professional rendering engine","description_ar":"محرك تطعيم احترافي","website":"https://www.chaos.com","download_url":"https://www.chaos.com/download","icon":"\U0001f3d7\ufe0f","alternatives_to":["Twinmotion","Lumion"],"platforms":["Windows","Mac"],"price":"$470/yr","version":"6"},
    {"id":"enscape","name":"Enscape","category":"render","type":"paid","description_en":"Real-time rendering plugin","description_ar":"إضافة تطعيم فوري","website":"https://enscape3d.com","download_url":"https://enscape3d.com/download/","icon":"\U0001f3d7\ufe0f","alternatives_to":["Twinmotion","Lumion"],"platforms":["Windows","Mac"],"price":"$539/yr","version":"4.1"},
    # AI Tools & Platforms
    {"id":"chatgpt","name":"ChatGPT","category":"ai","type":"free","description_en":"AI chatbot by OpenAI","description_ar":"روبوت محادثة بالذكاء الاصطناعي من OpenAI","website":"https://chat.openai.com","download_url":"https://chat.openai.com","icon":"\U0001f916","alternatives_to":["Claude","Gemini"],"platforms":["Web","Windows","Mac","Android","iOS"],"size":"Web","version":"4o"},
    {"id":"claude","name":"Claude AI","category":"ai","type":"free","description_en":"AI assistant by Anthropic","description_ar":"مساعد ذكي من Anthropic","website":"https://claude.ai","download_url":"https://claude.ai","icon":"\U0001f9a7","alternatives_to":["ChatGPT","Gemini"],"platforms":["Web","Windows","Mac"],"size":"Web","version":"3.5"},
    {"id":"gemini","name":"Google Gemini","category":"ai","type":"free","description_en":"Google AI assistant","description_ar":"مساعد جوجل الذكي","website":"https://gemini.google.com","download_url":"https://gemini.google.com","icon":"\u2728","alternatives_to":["ChatGPT","Claude"],"platforms":["Web","Android","iOS"],"size":"Web","version":"2.0"},
    {"id":"midjourney","name":"Midjourney","category":"ai","type":"paid","description_en":"AI image generation","description_ar":"توليد صور بالذكاء الاصطناعي","website":"https://www.midjourney.com","download_url":"https://www.midjourney.com","icon":"\U0001f3a8","alternatives_to":["DALL-E","Stable Diffusion"],"platforms":["Web","Discord"],"price":"$10/mo","version":"6.1"},
    {"id":"stable_diffusion","name":"Stable Diffusion","category":"ai","type":"free","description_en":"Open-source AI image generation","description_ar":"توليد صور مفتوح المصدر","website":"https://stability.ai","download_url":"https://github.com/AUTOMATIC1111/stable-diffusion-webui","icon":"\U0001f5bc\ufe0f","alternatives_to":["Midjourney","DALL-E"],"platforms":["Windows","Mac","Linux"],"size":"~7 GB","version":"XL 1.0"},
    {"id":"dalle","name":"DALL-E 3","category":"ai","type":"paid","description_en":"AI image generation by OpenAI","description_ar":"توليد صور من OpenAI","website":"https://openai.com/dall-e-3","download_url":"https://openai.com/dall-e-3","icon":"\U0001f9d1\u200d\U0001f3a8","alternatives_to":["Midjourney","Stable Diffusion"],"platforms":["Web"],"price":"$20/mo","version":"3"},
    {"id":"copilot","name":"Microsoft Copilot","category":"ai","type":"free","description_en":"Microsoft AI assistant","description_ar":"مساعد مايكروسوفت الذكي","website":"https://copilot.microsoft.com","download_url":"https://copilot.microsoft.com","icon":"\U0001f4bb","alternatives_to":["ChatGPT","Gemini"],"platforms":["Web","Windows","Edge"],"size":"Web","version":"2024"},
    {"id":"leonardo","name":"Leonardo AI","category":"ai","type":"free","description_en":"AI art platform","description_ar":"منصة فنية بالذكاء الاصطناعي","website":"https://leonardo.ai","download_url":"https://leonardo.ai","icon":"\U0001f3ad","alternatives_to":["Midjourney","Stable Diffusion"],"platforms":["Web"],"size":"Web","version":"2024"},
    {"id":"runway","name":"Runway ML","category":"ai","type":"paid","description_en":"AI video generation","description_ar":"توليد فيديو بالذكاء الاصطناعي","website":"https://runwayml.com","download_url":"https://runwayml.com","icon":"\U0001f3ac","alternatives_to":["Pika","Sora"],"platforms":["Web"],"price":"$12/mo","version":"Gen-3"},
    {"id":"pika","name":"Pika Labs","category":"ai","type":"free","description_en":"AI video generation","description_ar":"توليد فيديو مجاني","website":"https://pika.art","download_url":"https://pika.art","icon":"\U0001f3ac","alternatives_to":["Runway","Sora"],"platforms":["Web","Discord"],"size":"Web","version":"1.0"},
    {"id":"elevenlabs","name":"ElevenLabs","category":"ai","type":"free","description_en":"AI voice synthesis","description_ar":"تركيب صوت بالذكاء الاصطناعي","website":"https://elevenlabs.io","download_url":"https://elevenlabs.io","icon":"\U0001f399\ufe0f","alternatives_to":["Murf","Play.ht"],"platforms":["Web"],"size":"Web","version":"2024"},
    {"id":"notion_ai","name":"Notion AI","category":"ai","type":"paid","description_en":"AI writing in Notion","description_ar":"كتابة ذكية في Notion","website":"https://www.notion.so","download_url":"https://www.notion.so","icon":"\U0001f4dd","alternatives_to":["ChatGPT","Jasper"],"platforms":["Web","Windows","Mac"],"price":"$10/mo","version":"2024"},
    {"id":"perplexity","name":"Perplexity AI","category":"ai","type":"free","description_en":"AI search engine","description_ar":"محرك بحث ذكي","website":"https://www.perplexity.ai","download_url":"https://www.perplexity.ai","icon":"\U0001f50d","alternatives_to":["ChatGPT","Gemini"],"platforms":["Web","Android","iOS"],"size":"Web","version":"2024"},
    {"id":"cursor","name":"Cursor","category":"ai","type":"free","description_en":"AI code editor","description_ar":"محرر أكواد بالذكاء الاصطناعي","website":"https://cursor.sh","download_url":"https://cursor.sh","icon":"\U0001f4bb","alternatives_to":["Copilot","Codeium"],"platforms":["Windows","Mac","Linux"],"size":"~200 MB","version":"0.40"},
    {"id":"adobe_firefly","name":"Adobe Firefly","category":"ai","type":"paid","description_en":"Adobe AI image generation","description_ar":"توليد صور من Adobe","website":"https://firefly.adobe.com","download_url":"https://firefly.adobe.com","icon":"\U0001f3a8","alternatives_to":["Midjourney","DALL-E"],"platforms":["Web"],"price":"$4.99/mo","version":"3"},
]

COMPARISONS = {
    "architecture": [
        {"free": "FreeCAD", "paid": "ArchiCAD", "price": "$2,000+/yr", "diff": "ArchiCAD has more BIM features, FreeCAD is fully free"},
        {"free": "FreeCAD", "paid": "Revit", "price": "$2,545/yr", "diff": "Revit has better BIM workflow, FreeCAD is open-source"},
        {"free": "LibreCAD", "paid": "AutoCAD", "price": "$1,865/yr", "diff": "AutoCAD has more features, LibreCAD is free forever"},
    ],
    "design": [
        {"free": "GIMP", "paid": "Photoshop", "price": "$22.99/mo", "diff": "Photoshop has more tools, GIMP is free and open-source"},
        {"free": "Inkscape", "paid": "Illustrator", "price": "$22.99/mo", "diff": "Illustrator is industry standard, Inkscape is free"},
        {"free": "Krita", "paid": "Clip Studio Paint", "price": "$49.99", "diff": "Both great for digital painting, Krita is free"},
    ],
    "video": [
        {"free": "DaVinci Resolve", "paid": "Premiere Pro", "price": "$22.99/mo", "diff": "Resolve has better color grading, Premiere has better integration"},
        {"free": "Kdenlive", "paid": "Final Cut Pro", "price": "$299.99", "diff": "Final Cut is Mac-only, Kdenlive is free and cross-platform"},
    ],
    "audio": [
        {"free": "Audacity", "paid": "Adobe Audition", "price": "$22.99/mo", "diff": "Audition has more pro features, Audacity is simpler and free"},
        {"free": "LMMS", "paid": "FL Studio", "price": "$99-$499", "diff": "FL Studio is more polished, LMMS is completely free"},
    ],
    "3d": [
        {"free": "Blender", "paid": "Maya", "price": "$1,875/yr", "diff": "Maya is industry standard, Blender is free and powerful"},
        {"free": "Blender", "paid": "Cinema 4D", "price": "$719/yr", "diff": "Cinema 4D is easier to learn, Blender is free"},
    ],
    "render": [
        {"free": "Twinmotion", "paid": "Lumion", "price": "$1,625/yr", "diff": "Lumion has more content, Twinmotion is free for non-commercial"},
        {"free": "Kerkythea", "paid": "V-Ray", "price": "$470/yr", "diff": "V-Ray is industry standard, Kerkythea is free"},
    ],
    "office": [
        {"free": "LibreOffice", "paid": "Microsoft Office", "price": "$69.99/yr", "diff": "MS Office has better compatibility, LibreOffice is free"},
    ],
}

def reset_daily_if_needed(token_id):
    today = datetime.now().strftime("%Y-%m-%d")
    if usage_tracker[token_id]["reset_date"] != today:
        usage_tracker[token_id] = {"searches": 0, "downloads": 0, "reset_date": today}

def sanitize_input(text, max_len=200):
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', str(text))
    text = text.replace("'", "").replace('"', '').replace('&', '').replace(';', '')
    return text.strip()[:max_len]

def generate_token(api_key):
    token = secrets.token_hex(32)
    key_info = api_keys_store.get(api_key, {})
    expires_days = 30 if key_info.get("plan") == "monthly" else 365
    active_tokens[token] = {
        "api_key": api_key,
        "created": datetime.now().isoformat(),
        "expires": (datetime.now() + timedelta(days=expires_days)).isoformat(),
        "daily_downloads": key_info.get("daily_downloads", 3),
    }
    return token

def verify_token(token):
    if token not in active_tokens:
        return False
    info = active_tokens[token]
    if datetime.fromisoformat(info["expires"]) < datetime.now():
        del active_tokens[token]
        return False
    return True

def get_token_id(token):
    return hashlib.md5(token.encode()).hexdigest()[:12]

def title_match_score(expected, actual):
    if not expected or not actual:
        return 0.0
    exp = set(re.sub(r'[^a-z0-9\s]', '', expected.lower()).split())
    act = set(re.sub(r'[^a-z0-9\s]', '', actual.lower()).split())
    if not exp or not act:
        return 0.0
    return len(exp & act) / len(exp)

@asynccontextmanager
async def lifespan(app):
    logger.info("Application started")
    yield
    logger.info("Application shut down")

app = FastAPI(title="Movie Downloader Pro", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AuthRequest(BaseModel):
    api_key: str

class SearchRequest(BaseModel):
    query: str
    token: str

class ServerRequest(BaseModel):
    title: str
    year: str = ""
    token: str = ""
    tmdb_id: str = ""

class DownloadRequest(BaseModel):
    url: str
    quality: str = "best"
    token: str = ""
    save_dir: str = ""

class DownloadActionRequest(BaseModel):
    download_id: str
    token: str = ""

class QuranDownloadRequest(BaseModel):
    surah_number: int
    reciter: str = "alafasy"
    token: str = ""

class DownloadDirRequest(BaseModel):
    path: str
    token: str = ""

class AdminKeyRequest(BaseModel):
    admin_secret: str
    key: str
    plan: str = "monthly"
    days: int = 30
    daily_downloads: int = 5

class LicenseVerifyRequest(BaseModel):
    key: str
    hwid: str = ""

@app.get("/", response_class=HTMLResponse)
async def root():
    try:
        with open(resource_path("index.html"), "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        # fallback للمسار العادي
        with open("index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())

@app.post("/api/auth/login")
async def login(request: Request, body: AuthRequest):
    api_key = sanitize_input(body.api_key)
    if api_key not in api_keys_store:
        logger.warning(f"Failed login attempt: {api_key}")
        raise HTTPException(status_code=401, detail="Invalid key")
    key_info = api_keys_store[api_key]
    if not key_info.get("active"):
        raise HTTPException(status_code=403, detail="Key deactivated")
    token = generate_token(api_key)
    logger.info(f"Login successful for key: {api_key[:8]}...")
    return {"token": token, "plan": key_info["plan"], "expires": key_info["expires"], "daily_downloads": key_info["daily_downloads"]}

@app.post("/api/auth/verify")
async def verify_auth(request: Request, body: SearchRequest):
    if not verify_token(body.token):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return {"valid": True}

@app.post("/api/movies/search")
async def search_movies(request: Request, body: SearchRequest):
    token = body.token
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    token_id = get_token_id(token)
    reset_daily_if_needed(token_id)
    if usage_tracker[token_id]["searches"] >= DAILY_SEARCH_LIMIT:
        raise HTTPException(status_code=429, detail="Daily search limit reached")
    usage_tracker[token_id]["searches"] += 1

    query = sanitize_input(body.query)
    if not query:
        raise HTTPException(status_code=400, detail="Empty query")

    cache_key = hashlib.md5(f"movies:{query}".encode()).hexdigest()
    if cache_key in search_cache and time.time() - search_cache[cache_key]["time"] < CACHE_TTL:
        return {"candidates": search_cache[cache_key]["data"]}

    candidates = []
    if TMDB_API_KEY and TMDB_API_KEY != "YOUR_TMDB_API_KEY_HERE":
        try:
            search_url = "https://api.themoviedb.org/3/search/movie"
            params = {"api_key": TMDB_API_KEY, "query": query, "language": "ar-SA", "include_adult": False}
            resp = requests.get(search_url, params=params, timeout=5)
            if resp.status_code == 200:
                movies = resp.json().get("results", [])[:5]
                def fetch_detail(idx_m):
                    idx, m = idx_m
                    mid = m.get("id")
                    try:
                        det_resp = requests.get(f"https://api.themoviedb.org/3/movie/{mid}", params={"api_key": TMDB_API_KEY, "append_to_response": "credits", "language": "ar-SA"}, timeout=3).json()
                    except Exception:
                        det_resp = {}
                    crew = det_resp.get("credits", {}).get("crew", [])
                    cast = det_resp.get("credits", {}).get("cast", [])
                    directors = [c["name"] for c in crew if c.get("job") == "Director"]
                    top_cast = [c["name"] for c in cast[:4]]
                    pp = m.get("poster_path")
                    rd = m.get("release_date", "")
                    return {
                        "id": idx + 1, "tmdb_id": mid,
                        "title": m.get("title") or m.get("original_title", ""),
                        "year": rd.split("-")[0] if rd else "N/A",
                        "director": ", ".join(directors) or "N/A",
                        "cast": ", ".join(top_cast) or "N/A",
                        "synopsis": m.get("overview") or "N/A",
                        "poster_url": f"https://image.tmdb.org/t/p/w500{pp}" if pp else None,
                    }
                with ThreadPoolExecutor(max_workers=3) as ex:
                    candidates = list(ex.map(fetch_detail, enumerate(movies)))
        except Exception as e:
            logger.error(f"TMDB error: {e}")

    if not candidates:
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(f"{query} full movie film", max_results=5))
            for idx, r in enumerate(results):
                title_raw = r.get("title", query)
                clean = re.sub(r' - Wikipedia| - IMDb|\(\d{4}\)', '', title_raw).strip()
                year_match = re.search(r'\b(19\d\d|20\d\d)\b', title_raw + " " + r.get("body", ""))
                candidates.append({
                    "id": idx + 1, "title": clean,
                    "year": year_match.group(1) if year_match else "N/A",
                    "director": "N/A", "cast": "N/A",
                    "synopsis": r.get("body", "")[:200],
                    "poster_url": None,
                })
        except Exception as e:
            logger.error(f"Fallback search error: {e}")

    if not candidates:
        candidates.append({"id": 1, "title": query, "year": "N/A", "director": "N/A", "cast": "N/A", "synopsis": "Direct search.", "poster_url": None})

    logger.info(f"Movie search: '{query}' -> {len(candidates)} results")
    search_cache[cache_key] = {"data": candidates, "time": time.time()}
    return {"candidates": candidates}

@app.post("/api/movies/servers")
async def search_movie_servers(request: Request, body: ServerRequest):
    token = body.token
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    title = sanitize_input(body.title)
    year = sanitize_input(body.year)
    tmdb_id = sanitize_input(body.tmdb_id, 20)

    servers = []
    youtube_urls = []

    if tmdb_id and TMDB_API_KEY and TMDB_API_KEY != "YOUR_TMDB_API_KEY_HERE":
        try:
            vids_resp = requests.get(
                f"https://api.themoviedb.org/3/movie/{tmdb_id}/videos",
                params={"api_key": TMDB_API_KEY, "language": "en-US"},
                timeout=5
            )
            if vids_resp.status_code == 200:
                videos = vids_resp.json().get("results", [])
                for v in videos:
                    if v.get("site") == "YouTube" and v.get("key"):
                        youtube_urls.append(f"https://www.youtube.com/watch?v={v['key']}")

            if not youtube_urls:
                vids_resp2 = requests.get(
                    f"https://api.themoviedb.org/3/movie/{tmdb_id}/videos",
                    params={"api_key": TMDB_API_KEY},
                    timeout=5
                )
                if vids_resp2.status_code == 200:
                    for v in vids_resp2.json().get("results", []):
                        if v.get("site") == "YouTube" and v.get("key"):
                            youtube_urls.append(f"https://www.youtube.com/watch?v={v['key']}")
        except Exception as ex:
            logger.error(f"TMDB videos error: {ex}")

    def extract_url(url):
        return verify_and_extract(url)

    if youtube_urls:
        try:
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = {executor.submit(extract_url, u): u for u in youtube_urls[:10]}
                for future in as_completed(futures, timeout=15):
                    if len(servers) >= 6:
                        break
                    try:
                        info = future.result()
                        if info:
                            servers.append(info)
                    except Exception:
                        pass
        except Exception as ex:
            logger.error(f"YouTube extract error: {ex}")

    if not servers:
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                def quick_search(query):
                    try:
                        ydl_opts = {
                            "quiet": True, "no_warnings": True, "nocheckcertificate": True,
                            "noplaylist": True, "ignoreerrors": True, "socket_timeout": 8,
                            "retries": 1, "extract_flat": False,
                            "http_headers": {"User-Agent": "Mozilla/5.0"},
                        }
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            info = ydl.extract_info(f"ytsearch3:{query}", download=False)
                            if info and "entries" in info:
                                return [e["webpage_url"] for e in info["entries"] if e and e.get("webpage_url")]
                    except Exception:
                        pass
                    return []

                f1 = executor.submit(quick_search, f"{title} {year} full movie")
                f2 = executor.submit(quick_search, f"{title} full movie {year}")
                yt_urls = set()
                for f in [f1, f2]:
                    try:
                        yt_urls.update(f.result(timeout=12))
                    except Exception:
                        pass

                for u in list(yt_urls)[:6]:
                    if len(servers) >= 6:
                        break
                    try:
                        fi = executor.submit(extract_url, u)
                        info = fi.result(timeout=12)
                        if info:
                            servers.append(info)
                    except Exception:
                        pass
        except Exception as ex:
            logger.error(f"YT fallback error: {ex}")

    return {"servers": servers, "count": len(servers)}

@app.post("/api/music/search")
async def search_music(request: Request, body: SearchRequest):
    token = body.token
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    token_id = get_token_id(token)
    reset_daily_if_needed(token_id)
    if usage_tracker[token_id]["searches"] >= DAILY_SEARCH_LIMIT:
        raise HTTPException(status_code=429, detail="Daily search limit reached")
    usage_tracker[token_id]["searches"] += 1

    query = sanitize_input(body.query)
    if not query:
        raise HTTPException(status_code=400, detail="Empty query")

    results = []
    try:
        ydl_opts = {
            "quiet": True, "no_warnings": True, "nocheckcertificate": True,
            "noplaylist": True, "extract_flat": False,
            "http_headers": {"User-Agent": "Mozilla/5.0"},
        }
        search_url = f"ytsearch5:{query} music"
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_url, download=False)
            if info and "entries" in info:
                for idx, entry in enumerate(info["entries"]):
                    if not entry:
                        continue
                    results.append({
                        "id": idx + 1,
                        "title": entry.get("title", ""),
                        "url": entry.get("webpage_url") or entry.get("url", ""),
                        "duration": entry.get("duration_string", str(entry.get("duration", "N/A"))),
                        "thumbnail": entry.get("thumbnail"),
                        "uploader": entry.get("uploader", "Unknown"),
                    })
    except Exception as e:
        logger.error(f"Music search error: {e}")

    return {"tracks": results, "count": len(results)}

@app.post("/api/books/search")
async def search_books(request: Request, body: SearchRequest):
    token = body.token
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    token_id = get_token_id(token)
    reset_daily_if_needed(token_id)
    if usage_tracker[token_id]["searches"] >= DAILY_SEARCH_LIMIT:
        raise HTTPException(status_code=429, detail="Daily search limit reached")
    usage_tracker[token_id]["searches"] += 1

    query = sanitize_input(body.query)
    books = []
    try:
        search_url = f"https://archive.org/advancedsearch.php?q=title%3A({query.replace(' ', '+')})+mediatype%3Atexts&fl[]=identifier,title,creator,date,imagecount&sort[]=downloads+desc&rows=8&output=json"
        resp = requests.get(search_url, timeout=6)
        if resp.status_code == 200:
            docs = resp.json().get("response", {}).get("docs", [])
            for idx, doc in enumerate(docs):
                doc_id = doc.get("identifier", "")
                books.append({
                    "id": idx + 1,
                    "title": doc.get("title", ""),
                    "author": doc.get("creator", "Unknown"),
                    "date": doc.get("date", "N/A"),
                    "cover_url": f"https://archive.org/download/{doc_id}/page/N0_medium.jpg" if doc.get("imagecount", 0) > 0 else None,
                    "download_url": f"https://archive.org/details/{doc_id}",
                    "formats": [
                        {"name": "PDF", "url": f"https://archive.org/download/{doc_id}/{doc_id}.pdf"},
                        {"name": "EPUB", "url": f"https://archive.org/download/{doc_id}/{doc_id}.epub"},
                    ],
                })
    except Exception as e:
        logger.error(f"Book search error: {e}")

    if not books:
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(f"{query} filetype:pdf book free download", max_results=8))
            for idx, r in enumerate(results):
                books.append({
                    "id": idx + 1,
                    "title": r.get("title", "Unknown"),
                    "author": "Web Source",
                    "date": "N/A",
                    "download_url": r.get("href", ""),
                    "formats": [{"name": "PDF", "url": r.get("href", "")}],
                })
        except Exception:
            pass

    return {"books": books, "count": len(books)}

@app.get("/api/software/list")
async def software_list():
    return {"software": SOFTWARE_DB, "count": len(SOFTWARE_DB)}

@app.get("/api/software/{software_id}")
async def software_guide(software_id):
    sw = next((s for s in SOFTWARE_DB if s["id"] == software_id), None)
    if not sw:
        raise HTTPException(status_code=404, detail="Software not found")
    guide = {"install_steps_en": [], "install_steps_ar": []}
    if software_id == "freecad":
        guide = {
            "install_steps_en": [
                "Go to freecad.org/downloads.php",
                "Download the installer for your OS",
                "Run the installer",
                "Follow the setup wizard",
                "Choose installation directory",
                "Click Install and wait",
                "Launch FreeCAD"
            ],
            "install_steps_ar": [
                "اذهب إلى freecad.org/downloads.php",
                "حمل المثبت لنظام التشغيل الخاص بك",
                "شغّل المثبت",
                "اتبع معالج الإعداد",
                "اختر مجلد التثبيت",
                "انقر تثبيت وانتظر",
                "شغّل FreeCAD"
            ],
        }
    return {"software": sw, "guide": guide}

@app.get("/api/comparisons/{category}")
async def get_comparisons(category):
    items = COMPARISONS.get(category, [])
    return {"items": items, "count": len(items), "category": category}

@app.get("/api/quran/surahs")
async def quran_surahs():
    surahs = []
    for s in SURAHS:
        surahs.append({
            "number": s[0],
            "name_en": s[1],
            "name_ar": SURAH_AR.get(s[0], s[1]),
            "ayahs": s[2],
            "revelation": s[3],
        })
    return {"surahs": surahs, "count": len(surahs)}

@app.get("/api/quran/reciters")
async def quran_reciters():
    reciters = []
    for k, v in RECITERS.items():
        reciters.append({"id": k, "name_ar": v["name_ar"], "name_en": v["name_en"], "base_url": v["base_url"]})
    return {"reciters": reciters}

@app.post("/api/quran/download")
async def quran_download(request: Request, body: QuranDownloadRequest):
    token = body.token
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    surah_num = body.surah_number
    reciter_id = body.reciter

    if surah_num < 1 or surah_num > 114:
        raise HTTPException(status_code=400, detail="Invalid surah number")

    reciter = RECITERS.get(reciter_id)
    if not reciter:
        raise HTTPException(status_code=400, detail="Invalid reciter")

    padded = str(surah_num).zfill(3)
    audio_url = f"{reciter['base_url']}/{padded}.mp3"

    try:
        resp = requests.head(audio_url, timeout=5, allow_redirects=True)
        if resp.status_code != 200:
            raise HTTPException(status_code=404, detail="Audio file not found")
    except HTTPException:
        raise
    except Exception:
        pass

    dl_id = str(uuid.uuid4())[:12]
    save_dir = current_download_dir
    os.makedirs(save_dir, exist_ok=True)

    surah_info = SURAHS[surah_num - 1]
    filename = f"Quran_{padded}_{surah_info[1]}_{reciter['name_en']}.mp3"
    filepath = os.path.join(save_dir, filename)

    state = {
        "id": dl_id, "title": f"Quran - {surah_info[1]} - {reciter['name_ar']}",
        "url": audio_url, "filepath": filepath, "total": 0, "downloaded": 0,
        "speed": 0, "eta": 0, "status": "downloading", "error": "",
        "created_at": time.time(), "type": "quran",
    }
    with download_lock:
        active_downloads[dl_id] = state

    def download_quran():
        try:
            resp = requests.get(audio_url, stream=True, timeout=30)
            total = int(resp.headers.get('content-length', 0))
            state["total"] = total
            downloaded = 0
            with open(filepath, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if dl_id not in active_downloads or state["status"] == "paused":
                        state["status"] = "paused"
                        f.close()
                        return
                    f.write(chunk)
                    downloaded += len(chunk)
                    state["downloaded"] = downloaded
            state["status"] = "completed"
            logger.info(f"Quran download complete: {filename}")
        except Exception as e:
            state["status"] = "error"
            state["error"] = str(e)
            logger.error(f"Quran download error: {e}")

    t = threading.Thread(target=download_quran, daemon=True)
    t.start()

    return {"download_id": dl_id, "status": "downloading", "title": state["title"], "filepath": filepath}

# --- Quran: ترجمات و تتبع ---
QURAN_AYAH_CACHE = {}
@app.get("/api/quran/ayahs/{surah_number}")
async def quran_ayahs(surah_number: int, lang: str = "ar"):
    if surah_number < 1 or surah_number > 114:
        raise HTTPException(status_code=400, detail="Invalid surah")
    surah_info = SURAHS[surah_number-1]
    # جرب الكاش اولا
    cache_key = f"{surah_number}"
    if cache_key in QURAN_AYAH_CACHE:
        cached = QURAN_AYAH_CACHE[cache_key]
        # فلتر حسب اللغة المطلوبة لكن نرجع الكل
        return cached
    # حاول جلب من API الخارجي alquran.cloud (يوفر عربي + ان+فر+بر)
    ayahs = []
    try:
        resp = requests.get(f"https://api.alquran.cloud/v1/surah/{surah_number}/editions/quran-uthmani,en.sahih,fr.hamidullah,ber.mensur", timeout=12)
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            if len(data) >= 3:
                ar_list = data[0].get("ayahs", [])
                en_list = data[1].get("ayahs", [])
                fr_list = data[2].get("ayahs", []) if len(data)>2 else []
                ber_list = data[3].get("ayahs", []) if len(data)>3 else []
                for idx in range(len(ar_list)):
                    ar_text = ar_list[idx].get("text","").lstrip("\ufeff").strip()
                    en_text = en_list[idx].get("text","").strip() if idx < len(en_list) else ""
                    fr_text = fr_list[idx].get("text","").strip() if idx < len(fr_list) else ""
                    ber_text = ber_list[idx].get("text","").strip() if idx < len(ber_list) else ""
                    # fallback للترجمات المحلية للفاتحة والاخلاص اذا كانت اجود
                    local = QURAN_TRANSLATIONS.get(surah_number, {}).get(idx+1, {})
                    if local:
                        if local.get("en"): en_text = local["en"]
                        if local.get("fr"): fr_text = local["fr"]
                        if local.get("ber"): ber_text = local["ber"]
                    ayahs.append({"number": idx+1, "ar": ar_text, "en": en_text, "fr": fr_text, "ber": ber_text})
                result = {"surah": surah_number, "name": surah_info[1], "ayahs": ayahs, "lang": lang, "source": "api.alquran.cloud"}
                QURAN_AYAH_CACHE[cache_key] = result
                return result
    except Exception as e:
        logger.warning(f"Quran API fallback for surah {surah_number}: {e}")
    # fallback محلي
    trans = QURAN_TRANSLATIONS.get(surah_number, {})
    for i in range(1, surah_info[2]+1):
        t = trans.get(i, {"ar": "", "en": "", "fr": "", "ber": ""})
        # اذا لا توجد بيانات، استخدم نص عام
        ar = t.get("ar") or f"الآية {i} - سيتم تحميل النص عند الاتصال"
        en = t.get("en") or f"Verse {i}"
        fr = t.get("fr") or f"Verset {i}"
        ber = t.get("ber") or f"Aya {i} s tmazight"
        ayahs.append({"number": i, "ar": ar, "en": en, "fr": fr, "ber": ber})
    result = {"surah": surah_number, "name": surah_info[1], "ayahs": ayahs, "lang": lang, "source": "local"}
    QURAN_AYAH_CACHE[cache_key] = result
    return result

@app.get("/api/quran/info/{surah_number}")
async def quran_info(surah_number: int):
    if surah_number < 1 or surah_number > 114:
        raise HTTPException(status_code=400, detail="Invalid surah")
    s = SURAHS[surah_number-1]
    return {
        "number": s[0], "name_en": s[1], "ayahs": s[2], "revelation": s[3],
        "revelation_ar": "مكية" if s[3]=="Makkiyah" else "مدنية",
        "reason": QURAN_REASONS.get(surah_number, "سورة "+s[1]+" نزلت لحكمة يعلمها الله، فيها هداية وتشريع."),
        "tafsir": QURAN_TAFSIR.get(surah_number, "تفسير مختصر: "+s[1]+" فيها آيات التوحيد والعبادة. راجع ابن كثير والقرطبي."),
    }

# --- Hadith ---
class HadithSearchRequest(BaseModel):
    query: str = ""
    collection: str = "all"

@app.get("/api/hadith/collections")
async def hadith_collections():
    cols = list(set(h["collection"] for h in HADITH_DB))
    return {"collections": cols, "count": len(HADITH_DB)}

@app.get("/api/hadith/list")
async def hadith_list(collection: str = "all", limit: int = 20):
    if collection != "all":
        filtered = [h for h in HADITH_DB if collection in h["collection"]]
    else:
        filtered = HADITH_DB
    return {"hadiths": filtered[:limit], "count": len(filtered)}

@app.post("/api/hadith/search")
async def hadith_search(body: HadithSearchRequest):
    q = sanitize_input(body.query, 200).lower()
    coll = body.collection
    results = []
    for h in HADITH_DB:
        if coll != "all" and coll not in h["collection"]:
            continue
        hay = (h["text_ar"] + h["text_en"] + h["topic"] + h["narrator"]).lower()
        if not q or q in hay:
            results.append(h)
    return {"hadiths": results, "count": len(results)}

@app.get("/api/hadith/{hadith_id}")
async def hadith_detail(hadith_id: int):
    h = next((x for x in HADITH_DB if x["id"] == hadith_id), None)
    if not h:
        raise HTTPException(status_code=404, detail="Hadith not found")
    return h

@app.post("/api/hadith/download")
async def hadith_download(request: Request, body: QuranDownloadRequest):
    # نفس نظام تحميل القرآن لكن للنص
    token = body.token
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Invalid token")
    h = next((x for x in HADITH_DB if x["id"] == body.surah_number), None)
    if not h:
        raise HTTPException(status_code=404, detail="Hadith not found")
    dl_id = str(uuid.uuid4())[:12]
    filename = f"Hadith_{h['id']}_{h['topic']}.txt"
    filepath = os.path.join(current_download_dir, filename)
    os.makedirs(current_download_dir, exist_ok=True)
    content = f"{h['text_ar']}\n\nالراوي: {h['narrator']}\nالمصدر: {h['collection']} - {h['grade']}\nالشرح: {h['explanation_ar']}\n"
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    state = {"id": dl_id, "title": f"Hadith - {h['topic']}", "filepath": filepath, "total": len(content), "downloaded": len(content), "speed": 0, "eta": 0, "status": "completed", "error": ""}
    with download_lock:
        active_downloads[dl_id] = state
    return {"download_id": dl_id, "status": "completed", "title": state["title"]}

# --- Summary Card (بديل المقارنة) ---
@app.get("/api/summary/{kind}/{item_id}")
async def summary_card(kind: str, item_id: str):
    kind = sanitize_input(kind, 20)
    item_id = sanitize_input(item_id, 100)
    if kind == "quran":
        try:
            num = int(item_id)
            s = SURAHS[num-1]
            return {"kind": "quran", "title": s[1], "type": "مدنية" if s[3]=="Madaniyah" else "مكية", "ayahs": s[2], "reason": QURAN_REASONS.get(num,""), "tafsir": QURAN_TAFSIR.get(num,""), "revelation": s[3]}
        except:
            raise HTTPException(status_code=404, detail="Surah not found")
    elif kind == "hadith":
        h = next((x for x in HADITH_DB if str(x["id"])==item_id), None)
        if not h:
            raise HTTPException(status_code=404, detail="Hadith not found")
        return {"kind": "hadith", "title": h["topic"], "text_ar": h["text_ar"], "explanation": h["explanation_ar"], "grade": h["grade"], "collection": h["collection"]}
    elif kind == "software":
        sw = next((s for s in SOFTWARE_DB if s["id"]==item_id), None)
        if not sw:
            raise HTTPException(status_code=404, detail="Software not found")
        return {"kind": "software", "title": sw["name"], "summary": sw["description_ar"], "platforms": sw["platforms"], "size": sw["size"], "website": sw["website"]}
    else:
        return {"kind": kind, "id": item_id, "summary": f"ملخص {kind} - {item_id}", "note": "بطاقة تعريفية شاملة"}

@app.post("/api/download/start")
async def download_start(request: Request, body: DownloadRequest):
    token = body.token
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    token_id = get_token_id(token)
    reset_daily_if_needed(token_id)
    if usage_tracker[token_id]["downloads"] >= DAILY_DOWNLOAD_LIMIT:
        raise HTTPException(status_code=429, detail="Daily download limit reached")
    usage_tracker[token_id]["downloads"] += 1

    url = sanitize_input(body.url, 500)
    quality = sanitize_input(body.quality) or "best"
    save_dir = sanitize_input(body.save_dir, 500) or current_download_dir
    os.makedirs(save_dir, exist_ok=True)

    dl_id = str(uuid.uuid4())[:12]
    state = {
        "id": dl_id, "title": "Downloading...", "url": url,
        "filepath": "", "total": 0, "downloaded": 0,
        "speed": 0, "eta": 0, "status": "downloading", "error": "",
        "created_at": time.time(), "save_dir": save_dir, "quality": quality,
    }
    with download_lock:
        active_downloads[dl_id] = state

    def progress_hook(d):
        if dl_id not in active_downloads:
            return
        if d['status'] == 'downloading':
            state['downloaded'] = d.get('downloaded_bytes', 0) or 0
            state['total'] = d.get('total_bytes') or d.get('total_bytes_estimate', 0) or 0
            state['speed'] = d.get('speed', 0) or 0
            state['eta'] = d.get('eta', 0) or 0
            if d.get('_percent_str'):
                state['percent'] = d['_percent_str'].strip()
            if d.get('_filename'):
                state['title'] = os.path.basename(d['_filename'])
        elif d['status'] == 'finished':
            state['status'] = "completed"
            state['filepath'] = d.get('filename', '')
            state['title'] = os.path.basename(d.get('filename', 'Download complete'))
            state['percent'] = '100%'

    def run_download():
        # اصلاح 403 للكتب PDF - تحميل مباشر يتجاوز Cloudflare
        try:
            clean_url = url.split('?')[0].lower()
            if any(clean_url.endswith(ext) for ext in ['.pdf','.epub','.mobi','.docx','.zip','.rar','.7z','.txt']):
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36", "Referer": "https://google.com", "Accept": "*/*"}
                resp = requests.get(url, headers=headers, stream=True, timeout=30, verify=False)
                if resp.status_code == 200:
                    fname = url.split('/')[-1].split('?')[0] or "download.pdf"
                    fname = re.sub(r'[^\w\-_\.]', '_', fname)
                    if '.' not in fname:
                        fname += ".pdf"
                    if len(fname) < 5:
                        fname = f"book_{dl_id}.pdf"
                    filepath = os.path.join(save_dir, fname)
                    total = int(resp.headers.get('content-length', 0))
                    state["total"] = total
                    state["filepath"] = filepath
                    state["title"] = fname
                    downloaded = 0
                    with open(filepath, 'wb') as f:
                        for chunk in resp.iter_content(chunk_size=8192):
                            if dl_id not in active_downloads or state["status"] == "paused":
                                state["status"] = "paused"
                                return
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                state["downloaded"] = downloaded
                    state["status"] = "completed"
                    state["percent"] = "100%"
                    state["speed"] = 0
                    state["eta"] = 0
                    logger.info(f"Direct PDF download complete: {filepath}")
                    return
        except Exception as e:
            logger.warning(f"Direct download failed, fallback yt-dlp: {e}")

        has_ffmpeg = False
        try:
            import shutil
            has_ffmpeg = shutil.which("ffmpeg") is not None
        except Exception:
            pass

        format_spec = "best"
        if has_ffmpeg:
            format_spec = "bestvideo+bestaudio/best"
            if quality == "1080p":
                format_spec = "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best"
            elif quality == "720p":
                format_spec = "bestvideo[height<=720]+bestaudio/best[height<=720]/best"
            elif quality == "480p":
                format_spec = "bestvideo[height<=480]+bestaudio/best[height<=480]/best"
            elif quality == "360p":
                format_spec = "bestvideo[height<=360]+bestaudio/best[height<=360]/best"
        else:
            format_spec = "best[acodec!=none]/best"
            if quality == "1080p":
                format_spec = "best[height<=1080][acodec!=none]/best[acodec!=none]"
            elif quality == "720p":
                format_spec = "best[height<=720][acodec!=none]/best[acodec!=none]"
            elif quality == "480p":
                format_spec = "best[height<=480][acodec!=none]/best[acodec!=none]"
            elif quality == "360p":
                format_spec = "best[height<=360][acodec!=none]/best[acodec!=none]"
        if quality == "mp3":
            format_spec = "bestaudio/best"

        out_template = os.path.join(save_dir, "%(title)s.%(ext)s")
        ydl_opts = {
            "format": format_spec,
            "outtmpl": out_template,
            "progress_hooks": [progress_hook],
            "quiet": True, "no_warnings": True, "nocheckcertificate": True,
            "retries": 3, "http_headers": {"User-Agent": "Mozilla/5.0"},
            "extractor_args": {"youtube": {"player_client": ["android"]}},
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                state['filepath'] = ydl.prepare_filename(info)
                state['title'] = info.get('title', 'Download complete')
                state['status'] = "completed"
                state['percent'] = '100%'
            logger.info(f"Download complete: {state['filepath']}")
        except Exception as e:
            if dl_id in active_downloads:
                state['status'] = "error"
                state['error'] = str(e)
                logger.error(f"Download error: {e}")

    t = threading.Thread(target=run_download, daemon=True)
    t.start()

    return {"download_id": dl_id, "status": "downloading"}

@app.get("/api/download/{dl_id}/progress")
async def download_progress(dl_id):
    state = active_downloads.get(dl_id)
    if not state:
        raise HTTPException(status_code=404, detail="Download not found")
    percent = 0
    if state.get("total", 0) > 0:
        percent = round((state.get("downloaded", 0) / state["total"]) * 100, 1)
    elif state.get("percent"):
        try:
            percent = float(state["percent"].replace('%', ''))
        except Exception:
            percent = 0
    return {
        "id": state["id"],
        "title": state.get("title", ""),
        "status": state["status"],
        "percent": percent,
        "total": state.get("total", 0),
        "downloaded": state.get("downloaded", 0),
        "speed": state.get("speed", 0),
        "eta": state.get("eta", 0),
        "filepath": state.get("filepath", ""),
        "save_dir": state.get("save_dir", current_download_dir),
        "error": state.get("error", ""),
        "url": state.get("url", ""),
    }

@app.post("/api/download/pause")
async def download_pause(request: Request, body: DownloadActionRequest):
    token = body.token
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    state = active_downloads.get(body.download_id)
    if not state:
        raise HTTPException(status_code=404, detail="Download not found")
    state["status"] = "paused"
    return {"status": "paused", "download_id": body.download_id}

@app.post("/api/download/resume")
async def download_resume(request: Request, body: DownloadActionRequest):
    token = body.token
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    state = active_downloads.get(body.download_id)
    if not state:
        raise HTTPException(status_code=404, detail="Download not found")
    if state["status"] != "paused":
        raise HTTPException(status_code=400, detail="Download is not paused")

    url = state.get("url", "")
    save_dir = state.get("save_dir", current_download_dir)
    quality = state.get("quality", "best")

    state["status"] = "downloading"
    state["error"] = ""

    def progress_hook(d):
        if d['status'] == 'downloading':
            state['downloaded'] = d.get('downloaded_bytes', 0) or 0
            state['total'] = d.get('total_bytes') or d.get('total_bytes_estimate', 0) or 0
            state['speed'] = d.get('speed', 0) or 0
            state['eta'] = d.get('eta', 0) or 0
            if d.get('_percent_str'):
                state['percent'] = d['_percent_str'].strip()
        elif d['status'] == 'finished':
            state['status'] = "completed"
            state['filepath'] = d.get('filename', '')
            state['title'] = os.path.basename(d.get('filename', 'Download complete'))
            state['percent'] = '100%'

    def run_download():
        has_ffmpeg = False
        try:
            import shutil
            has_ffmpeg = shutil.which("ffmpeg") is not None
        except Exception:
            pass

        format_spec = "best"
        if has_ffmpeg:
            format_spec = "bestvideo+bestaudio/best"
            if quality == "1080p":
                format_spec = "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best"
            elif quality == "720p":
                format_spec = "bestvideo[height<=720]+bestaudio/best[height<=720]/best"
            elif quality == "480p":
                format_spec = "bestvideo[height<=480]+bestaudio/best[height<=480]/best"
            elif quality == "360p":
                format_spec = "bestvideo[height<=360]+bestaudio/best[height<=360]/best"
        else:
            format_spec = "best[acodec!=none]/best"
            if quality == "1080p":
                format_spec = "best[height<=1080][acodec!=none]/best[acodec!=none]"
            elif quality == "720p":
                format_spec = "best[height<=720][acodec!=none]/best[acodec!=none]"
            elif quality == "480p":
                format_spec = "best[height<=480][acodec!=none]/best[acodec!=none]"
            elif quality == "360p":
                format_spec = "best[height<=360][acodec!=none]/best[acodec!=none]"
        if quality == "mp3":
            format_spec = "bestaudio/best"

        out_template = os.path.join(save_dir, "%(title)s.%(ext)s")
        ydl_opts = {
            "format": format_spec,
            "outtmpl": out_template,
            "progress_hooks": [progress_hook],
            "continuedl": True,
            "quiet": True, "no_warnings": True, "nocheckcertificate": True,
            "retries": 3, "http_headers": {"User-Agent": "Mozilla/5.0"},
            "extractor_args": {"youtube": {"player_client": ["android"]}},
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                state['filepath'] = ydl.prepare_filename(info)
                state['title'] = info.get('title', 'Download complete')
                state['status'] = "completed"
                state['percent'] = '100%'
            logger.info(f"Download resumed and complete: {state['filepath']}")
        except Exception as e:
            if body.download_id in active_downloads:
                state['status'] = "error"
                state['error'] = str(e)
                logger.error(f"Resume download error: {e}")

    t = threading.Thread(target=run_download, daemon=True)
    t.start()
    return {"status": "resuming", "download_id": body.download_id}

@app.post("/api/download/cancel")
async def download_cancel(request: Request, body: DownloadActionRequest):
    token = body.token
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    state = active_downloads.get(body.download_id)
    if not state:
        raise HTTPException(status_code=404, detail="Download not found")
    state["status"] = "cancelled"
    filepath = state.get("filepath", "")
    if filepath and os.path.exists(filepath):
        try:
            os.remove(filepath)
        except Exception:
            pass
    with download_lock:
        del active_downloads[body.download_id]
    return {"status": "cancelled", "download_id": body.download_id}

@app.post("/api/admin/create-key")
async def admin_create_key(request: Request, body: AdminKeyRequest):
    if body.admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Invalid admin secret")
    api_keys_store[body.key] = {
        "plan": body.plan,
        "expires": (datetime.now() + timedelta(days=body.days)).strftime("%Y-%m-%d"),
        "daily_downloads": body.daily_downloads,
        "active": True,
    }
    logger.info(f"Admin created key: {body.key[:8]}...")
    return {"status": "created", "key": body.key, "plan": body.plan, "expires": api_keys_store[body.key]["expires"]}

@app.post("/api/settings/download-dir")
async def set_download_dir(request: Request, body: DownloadDirRequest):
    global current_download_dir
    token = body.token
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    new_path = sanitize_input(body.path, 500)
    if not new_path:
        raise HTTPException(status_code=400, detail="Empty path")
    os.makedirs(new_path, exist_ok=True)
    current_download_dir = new_path
    logger.info(f"Download dir changed to: {new_path}")
    return {"download_dir": current_download_dir}

@app.get("/api/settings/download-dir")
async def get_download_dir():
    return {"download_dir": current_download_dir}

@app.get("/api/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat(), "download_dir": current_download_dir}

@app.post("/api/license/verify")
async def license_verify(body: LicenseVerifyRequest):
    """تحقق من مفتاح الترخيص للـ EXE - يدعم التحقق عن بعد"""
    key = body.key.strip().upper()
    info = api_keys_store.get(key)
    if not info:
        return JSONResponse({"valid": False, "reason": "المفتاح غير موجود"})
    if not info.get("active"):
        return JSONResponse({"valid": False, "reason": "المفتاح معطل"})
    try:
        exp = datetime.strptime(info["expires"], "%Y-%m-%d")
        if exp < datetime.now():
            return JSONResponse({"valid": False, "reason": f"انتهى في {info['expires']}"})
    except:
        pass
    return {"valid": True, "plan": info["plan"], "expires": info["expires"], "daily_downloads": info["daily_downloads"], "hwid": body.hwid}

@app.get("/api/downloads/active")
async def list_active_downloads():
    downloads = []
    for dl_id, state in active_downloads.items():
        percent = 0
        if state.get("total", 0) > 0:
            percent = round((state.get("downloaded", 0) / state["total"]) * 100, 1)
        downloads.append({
            "id": dl_id,
            "title": state.get("title", ""),
            "status": state["status"],
            "percent": percent,
            "total": state.get("total", 0),
            "downloaded": state.get("downloaded", 0),
            "speed": state.get("speed", 0),
            "eta": state.get("eta", 0),
        })
    return {"downloads": downloads, "count": len(downloads)}

AD_BLACKLIST = ["doubleclick.net", "google-analytics.com", "googlesyndication.com", "popads.net"]

def extract_links_bs4(url):
    found = set()
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(url, headers=headers, timeout=6)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup.find_all(["video", "source"]):
                src = tag.get("src")
                if src and any(ext in src.lower() for ext in [".mp4", ".m3u8", ".mpd"]):
                    found.add(src)
            for script in soup.find_all("script"):
                if script.string:
                    for match in re.findall(r'https?://[^\s\'"]+?\.(?:m3u8|mp4|mpd)[^\s\'"]*', script.string):
                        if not any(b in match.lower() for b in AD_BLACKLIST):
                            found.add(match)
    except Exception:
        pass
    return found

def verify_and_extract(url, expected_title="", fallback_title="Unknown"):
    ydl_opts = {
        "quiet": True, "no_warnings": True, "nocheckcertificate": True,
        "noplaylist": True, "ignoreerrors": True, "socket_timeout": 8,
        "retries": 1, "http_headers": {"User-Agent": "Mozilla/5.0"},
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return None
            if "entries" in info and info["entries"]:
                info = info["entries"][0]
            duration = info.get("duration", 0) or 0
            if 0 < duration < 300:
                return None
            extracted_title = info.get("title", "")
            resolution = info.get("format_note") or info.get("resolution")
            if not resolution or resolution == "N/A":
                w, h = info.get("width"), info.get("height")
                resolution = f"{w}x{h}" if w and h else "HD"
            filesize = info.get("filesize") or info.get("filesize_approx")
            return {
                "title": extracted_title or fallback_title,
                "url": url,
                "duration": f"{duration // 3600}h {(duration % 3600) // 60}m" if duration else "N/A",
                "resolution": resolution,
                "ext": info.get("ext", "mp4"),
                "size": f"{filesize / (1024*1024):.1f} MB" if filesize else "N/A",
                "year": info.get("release_year") or (info.get("upload_date") or "")[:4] or "N/A",
            }
    except Exception:
        return None
