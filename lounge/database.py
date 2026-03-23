import json
import os
import random
from datetime import date

DATA_FILE = os.path.join(os.path.dirname(__file__), "lounge_data.json")


def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {
        "users": {},
        "confessions": [],
        "alter_ego_queue": [],
        "alter_ego_matches": {},
        "alter_ego_names": {},
        "lotto_participants": [],
        "last_lotto_date": None,
        "last_poll_date": None,
        "confession_count": 0,
    }


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)


def get_user(data, user_id):
    uid = str(user_id)
    if uid not in data["users"]:
        data["users"][uid] = {
            "points": 100,
            "title": "Lurker",
            "chaos_score": 0,
            "wisdom_score": 0,
            "confession_count": 0,
            "lotto_wins": 0,
            "joined": str(date.today()),
        }
    return data["users"][uid]


def update_points(data, user_id, amount):
    user = get_user(data, user_id)
    user["points"] = max(0, user["points"] + amount)
    _update_title(user)
    save_data(data)
    return user["points"]


def _update_title(user):
    points = user["points"]
    if points >= 1000:
        user["title"] = "Overlord"
    elif points >= 500:
        user["title"] = "King"
    elif points >= 300:
        user["title"] = "Villain"
    elif points >= 200:
        user["title"] = "Hustler"
    elif points >= 150:
        user["title"] = "Climber"
    elif points >= 100:
        user["title"] = "Lurker"
    elif points >= 50:
        user["title"] = "Broke Boy"
    else:
        user["title"] = "Ghost"


DAILY_POLLS = [
    ("Er det ok at ghoste nogen efter 1 date?", ["Ja, helt ok", "Nej, det er fejthed", "Kommer an på det"]),
    ("Ville du lyve for at beskytte en ven?", ["Ja, altid", "Nej, aldrig", "Kun små løgne"]),
    ("Er jalousi attraktivt?", ["Ja, det viser omsorg", "Nej, det er giftig", "Lidt er ok"]),
    ("Hvad er vigtigst i et forhold?", ["Ærlighed", "Tillid", "Tiltrækning", "Humor"]),
    ("Ville du date en ex igen?", ["Ja, folk ændrer sig", "Nej, ex er ex", "Måske, hvis det var godt"]),
    ("Er det ok at tjekke partnerens telefon?", ["Ja, hvis man har tilladelse", "Nej, aldrig", "Kun ved mistanke"]),
    ("Hvornår er selvtillid arrogance?", ["Aldrig", "Når man ser ned på andre", "Når man snakker for meget om sig selv"]),
    ("Er det ok at have venner af det modsatte køn?", ["Ja, selvfølgelig", "Nej, det skaber problemer", "Ja, men med grænser"]),
    ("Red flag eller green flag: Han/hun svarer ikke i timevis?", ["Red flag", "Green flag", "Ligegyldigt"]),
    ("Hvad er mere attraktivt?", ["Ærlighed", "Mystik", "Ambition", "Humor"]),
    ("Ville du forlade en relation for din drømmejob i udlandet?", ["Ja", "Nej", "Vi ville ordne det"]),
    ("Er sociale medier godt eller dårligt for dating?", ["Godt", "Dårligt", "Begge dele"]),
    ("Hvad giver dig mest adrenalin?", ["Risiko", "Ny kærlighed", "Sport", "Penge"]),
    ("Er det ok at sige 'jeg elsker dig' først?", ["Ja, mod er attraktivt", "Nej, vent", "Det afhænger af timing"]),
    ("Hvad er en deal-breaker?", ["Rygning", "Dårlig hygiejne", "Ingen ambitioner", "Voldsom jalousi"]),
    ("Hvem betaler på første date?", ["Den der inviterede", "Del altid", "Manden betaler", "Den rigeste"]),
    ("Er det ok at snuse på en dates sociale medier?", ["Ja, alle gør det", "Nej, det er creepy", "Kun det offentlige"]),
    ("Hvad er vigtigere?", ["At have ret", "At have fred", "At have begge dele"]),
    ("Kan mænd og kvinder være venner uden romantiske følelser?", ["Ja, altid", "Nej, altid følelser", "Det er svært"]),
    ("Er det ok at lyve om sin alder på dating apps?", ["Ja, alle gør det", "Nej, aldrig", "Kun lidt"]),
]

SPIN_OUTCOMES = [
    ("win", "Du vinder 50 points! Du er på en winning streak 🔥", 50),
    ("win", "Lille gevinst — +25 points. Bedre end ingenting 😏", 25),
    ("win", "Jackpot! +100 points! Du er dagens held 🎰", 100),
    ("win", "+75 points! Held er på din side i dag 🍀", 75),
    ("lose", "Du mister 30 points. Spillet er hårdt 😬", -30),
    ("lose", "Ouch! -50 points. Lady Luck er ikke din veninde 😅", -50),
    ("lose", "Du taber 20 points 💀", -20),
    ("special", "Du skal skrive en pinlig sandhed i gruppen for at beholde dine points! 🎭", 0),
    ("special", "Du vinder titlen 'Lucky Bastard' midlertidigt +75 points 🏆", 75),
    ("special", "Du mister din nuværende titel! Tilbage til start -40 points 😱", -40),
]

ALTER_EGO_NAMES = [
    "Skyggen fra Østerbro", "Den mystiske Baron", "Midnatens Dronning",
    "Den anonyme Filosof", "Nattens Løve", "Den farlige Drømmer",
    "Det skjulte Geni", "Byens Vildkat", "Den tavse Storm",
    "Havnens Spøgelse", "Den hviskende Rebel", "Midtbyens Haj",
    "Den forsvundne Prins", "Nattens Seer", "Dybets Stemme",
    "Den maskerede Agent", "Skumringens Mester", "Den skjulte Kraft",
    "Byens Skygge", "Den mørke Ridder", "Havets Hemmelighed",
    "Den tavse Dommer", "Nattens Jæger", "Det ukendte Ansigt",
]
