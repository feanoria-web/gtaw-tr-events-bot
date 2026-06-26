"""
GTAW:TR Events Team Discord Botu
=================================
Komutlar:
  /event create <name> <date> [description]  - Event olustur ve duyur
  /event admin  <event_id> <user>            - Event'e admin ata

Ozellikler:
  - Event duyurusu + Events Team etiketi + Katil butonu
  - Hak talebi menusu (NC hakki, +1 karakter slotu) - ephemeral
  - Admin checklist DM ile gonderilir (Feanor, LFM, faction, management)
  - Checklist hatirlatici: event'ten 2 gun once, 8 saatte bir DM
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import re
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("gtaw_events")

TOKEN = os.getenv("DISCORD_TOKEN", "")
EVENTS_TEAM_ROLE_ID = int(os.getenv("EVENTS_TEAM_ROLE_ID", "0"))

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# ---------------------------------------------------------------------------
# Veri Yonetimi
# ---------------------------------------------------------------------------

DATA_FILE = "events.json"
events_db: dict[str, dict] = {}

CHECKLIST_ITEMS: list[tuple[str, str]] = [
    ("feanor_approval",     "Feanor'un onayi alindi"),
    ("lfm_approval",        "LFM'in tam onayi alindi"),
    ("faction_briefed",     "Ilgili olusumun detayli plandan haberi var"),
    ("management_approval", "Management onayi alindi (buyuk kapsamli eventler icin)"),
]


def _parse_iso(s) -> datetime | None:
    return datetime.fromisoformat(s) if isinstance(s, str) and s else None


def load_data():
    global events_db
    if not os.path.exists(DATA_FILE):
        return
    with open(DATA_FILE, encoding="utf-8") as f:
        raw: dict = json.load(f)
    for ev in raw.values():
        ev["date"]          = _parse_iso(ev.get("date"))
        ev["last_reminder"] = _parse_iso(ev.get("last_reminder"))
    events_db = raw
    log.info("Yuklendi: %d event", len(events_db))


def save_data():
    out = {}
    for eid, ev in events_db.items():
        e = dict(ev)
        e["date"]          = e["date"].isoformat()          if isinstance(e.get("date"), datetime)          else None
        e["last_reminder"] = e["last_reminder"].isoformat() if isinstance(e.get("last_reminder"), datetime) else None
        out[eid] = e
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:20]


def make_event_id(name: str) -> str:
    base = slugify(name) or "event"
    eid, n = base, 1
    while eid in events_db:
        eid, n = f"{base}_{n}", n + 1
    return eid


# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------

WARNING_TEXT = (
    "\n\n\u26a0\ufe0f **UYARI:** Size daha onceden verilmis haklar varken ve bunlari "
    "kullanmiyorken boyle seyler talep etmeniz **ekipten uzaklastirilmanizla** "
    "sonuclanabilir. Talebinizi gondermeden once mevcut haklarinizi kontrol edin."
)

RIGHTS_OPTIONS = [
    discord.SelectOption(
        label="NC Hakki Istiyorum",
        description="Non-Combatant statusu talep et",
        value="nc_right",
        emoji="\U0001f6e1\ufe0f",
    ),
    discord.SelectOption(
        label="+1 Karakter Slotu Istiyorum",
        description="Ekstra karakter slotu talep et",
        value="char_slot",
        emoji="\U0001f464",
    ),
]
RIGHTS_LABELS = {
    "nc_right":  "NC (Non-Combatant) Hakki",
    "char_slot": "+1 Karakter Slotu",
}

# ---------------------------------------------------------------------------
# Views - Hak Talebi (Ephemeral)
# ---------------------------------------------------------------------------


class RightsSelect(discord.ui.Select):
    def __init__(self, event_id: str):
        super().__init__(
            placeholder="Bir hak talebi secin...",
            options=RIGHTS_OPTIONS,
            custom_id=f"rs:{event_id}",
        )
        self.event_id = event_id

    async def callback(self, interaction: discord.Interaction):
        ev     = events_db.get(self.event_id)
        chosen = RIGHTS_LABELS[self.values[0]]

        await interaction.response.send_message(
            f"\U0001f4cb **{chosen}** talebiniz alindi ve event adminine iletildi!{WARNING_TEXT}",
            ephemeral=True,
        )

        if ev and ev.get("admin_id"):
            try:
                guild = interaction.guild
                admin = guild.get_member(ev["admin_id"]) if guild else None
                if admin:
                    await admin.send(
                        f"\U0001f4e9 **{interaction.user.display_name}** (`{interaction.user}`), "
                        f"**{ev['name']}** eventi icin **{chosen}** talep etti."
                    )
            except Exception as exc:
                log.warning("Admin DM hatasi: %s", exc)


class RightsView(discord.ui.View):
    """Katil butonuna basin kisi icin acilan ephemeral menu."""

    def __init__(self, event_id: str):
        super().__init__(timeout=300)
        self.add_item(RightsSelect(event_id))


# ---------------------------------------------------------------------------
# Views - Katil Butonu (Kalici / Persistent)
# ---------------------------------------------------------------------------


class JoinButton(discord.ui.Button):
    def __init__(self, event_id: str):
        super().__init__(
            label="Katil / Hak Talep Et",
            style=discord.ButtonStyle.green,
            emoji="\u270b",
            custom_id=f"join:{event_id}",
        )
        self.event_id = event_id

    async def callback(self, interaction: discord.Interaction):
        ev = events_db.get(self.event_id)
        if not ev:
            await interaction.response.send_message(
                "Bu event artik mevcut degil.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"\U0001f389 {ev['name']} \u2014 Hak Talebi",
            description=(
                "Asagidan bir hak talebi secebilirsiniz:\n\n"
                "\U0001f6e1\ufe0f **NC Hakki Istiyorum** \u2014 Non-Combatant statusu talep et\n"
                "\U0001f464 **+1 Karakter Slotu Istiyorum** \u2014 Ekstra karakter slotu talep et"
                + WARNING_TEXT
            ),
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(
            embed=embed,
            view=RightsView(self.event_id),
            ephemeral=True,
        )


class JoinView(discord.ui.View):
    """Event duyurusuna eklenen kalici buton view'i."""

    def __init__(self, event_id: str):
        super().__init__(timeout=None)
        self.add_item(JoinButton(event_id))


# ---------------------------------------------------------------------------
# Views - Checklist (Kalici / Persistent)
# ---------------------------------------------------------------------------


def build_checklist_embed(ev: dict) -> discord.Embed:
    cl   = ev.get("checklist", {})
    done = sum(1 for k, _ in CHECKLIST_ITEMS if cl.get(k))
    desc = "\n".join(
        f"{'[x]' if cl.get(k) else '[ ]'}  {lbl}"
        for k, lbl in CHECKLIST_ITEMS
    )
    # Emoji versiyonu
    desc = "\n".join(
        f"{'\u2705' if cl.get(k) else '\u2b1c'}  {lbl}"
        for k, lbl in CHECKLIST_ITEMS
    )
    all_done = done == len(CHECKLIST_ITEMS)
    embed = discord.Embed(
        title=f"\U0001f4cb {ev['name']} \u2014 Event Checklist ({done}/{len(CHECKLIST_ITEMS)})",
        description=desc,
        color=discord.Color.green() if all_done else discord.Color.blurple(),
    )
    if all_done:
        embed.add_field(
            name="\u2705 Checklist Tamamlandi!",
            value="Tum onaylar alindi. Event hazir.",
            inline=False,
        )
    if ev.get("date"):
        embed.set_footer(text=f"Event tarihi: {ev['date'].strftime('%d/%m/%Y %H:%M')}")
    return embed


class ChecklistButton(discord.ui.Button):
    def __init__(self, event_id: str, key: str, label: str, checked: bool):
        super().__init__(
            label=f"{'\u2705' if checked else '\u2b1c'}  {label}",
            style=discord.ButtonStyle.green if checked else discord.ButtonStyle.grey,
            custom_id=f"cl:{event_id}:{key}",
        )
        self.event_id = event_id
        self.key      = key

    async def callback(self, interaction: discord.Interaction):
        ev = events_db.get(self.event_id)
        if not ev:
            await interaction.response.send_message("Event bulunamadi.", ephemeral=True)
            return
        if interaction.user.id != ev.get("admin_id"):
            await interaction.response.send_message(
                "\u274c Sadece event admini bu listeyi degistirebilir!", ephemeral=True
            )
            return

        cl = ev.setdefault("checklist", {})
        cl[self.key] = not cl.get(self.key, False)
        save_data()

        new_view = ChecklistView(self.event_id)
        bot.add_view(new_view)
        await interaction.response.edit_message(embed=build_checklist_embed(ev), view=new_view)


class ChecklistView(discord.ui.View):
    """Admin icin DM'e gonderilen, tiklanabilir checklist view'i."""

    def __init__(self, event_id: str):
        super().__init__(timeout=None)
        ev = events_db.get(event_id, {})
        cl = ev.get("checklist", {})
        for key, lbl in CHECKLIST_ITEMS:
            self.add_item(ChecklistButton(event_id, key, lbl, bool(cl.get(key))))


# ---------------------------------------------------------------------------
# Bot Sinifi
# ---------------------------------------------------------------------------


class GTAWEventsBot(commands.Bot):
    async def setup_hook(self):
        load_data()
        # Bot yeniden baslatildiginda kalici view'leri yeniden kaydet
        for eid, ev in events_db.items():
            self.add_view(JoinView(eid))
            if ev.get("admin_id"):
                self.add_view(ChecklistView(eid))
        self.tree.add_command(event_group)
        await self.tree.sync()
        log.info("Slash komutlari senkronize edildi.")

    async def on_ready(self):
        if not reminder_task.is_running():
            reminder_task.start()
        log.info(
            "Bot hazir: %s | %d sunucu | Prefix: ! | Slash komutlar aktif",
            self.user,
            len(self.guilds),
        )
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching, name="GTAW:TR Events"
            )
        )


bot = GTAWEventsBot(command_prefix="!", intents=intents)

# ---------------------------------------------------------------------------
# Slash Komutlari
# ---------------------------------------------------------------------------

event_group = app_commands.Group(
    name="event",
    description="GTAW:TR Events Team komutlari",
)


def parse_date(s: str) -> datetime | None:
    for fmt in ("%d/%m/%Y %H:%M", "%d.%m.%Y %H:%M", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


@event_group.command(name="create", description="Yeni bir event olustur ve duyur")
@app_commands.describe(
    name="Event adi",
    date="Event tarihi (or: 25/07/2025 20:00)",
    description="Event aciklamasi (istege bagli)",
)
async def cmd_create(
    interaction: discord.Interaction,
    name: str,
    date: str,
    description: str = "",
):
    dt = parse_date(date)
    if not dt:
        await interaction.response.send_message(
            "\u274c Tarih formati hatali. Ornek: `25/07/2025 20:00` veya `25.07.2025 20:00`",
            ephemeral=True,
        )
        return

    eid = make_event_id(name)
    events_db[eid] = {
        "name":          name,
        "description":   description,
        "date":          dt,
        "creator_id":    interaction.user.id,
        "admin_id":      None,
        "checklist":     {k: False for k, _ in CHECKLIST_ITEMS},
        "last_reminder": None,
        "guild_id":      interaction.guild_id,
    }
    save_data()

    role_ping = f"<@&{EVENTS_TEAM_ROLE_ID}>" if EVENTS_TEAM_ROLE_ID else "**@Events Team**"

    embed = discord.Embed(
        title=f"\U0001f389 Yeni Event: {name}",
        description=description or "Detaylar yakinda paylasila cak.",
        color=discord.Color.green(),
    )
    embed.add_field(name="\U0001f4c5 Tarih",    value=dt.strftime("%d/%m/%Y %H:%M"), inline=True)
    embed.add_field(name="\U0001f194 Event ID", value=f"`{eid}`",                    inline=True)
    embed.set_footer(text="Katilmak veya hak talep etmek icin asagidaki butona basin.")
    embed.set_author(
        name=f"Olusturan: {interaction.user.display_name}",
        icon_url=interaction.user.display_avatar.url,
    )

    view = JoinView(eid)
    bot.add_view(view)
    await interaction.response.send_message(
        content=f"{role_ping} \U0001f4e2 Yeni bir event duyuruldu!",
        embed=embed,
        view=view,
    )
    log.info("Event olusturuldu: %s (%s) - %s", name, eid, dt.strftime("%d/%m/%Y %H:%M"))


@event_group.command(name="admin", description="Bir evente admin ata")
@app_commands.describe(
    event_id="Event ID'si (olusturulurken gosterilen ID)",
    user="Admin olarak atanacak kullanici",
)
async def cmd_admin(interaction: discord.Interaction, event_id: str, user: discord.Member):
    ev = events_db.get(event_id)
    if not ev:
        await interaction.response.send_message(
            f"\u274c `{event_id}` ID'li event bulunamadi.\n"
            "Ipucu: Event ID'sini otomatik tamamlama ile secebilirsiniz.",
            ephemeral=True,
        )
        return

    old_admin = ev.get("admin_id")
    ev["admin_id"] = user.id
    save_data()

    cl_view = ChecklistView(event_id)
    bot.add_view(cl_view)
    embed = build_checklist_embed(ev)
    embed.set_author(name=f"Admin: {user.display_name}", icon_url=user.display_avatar.url)

    dm_text = (
        f"\U0001f3d6\ufe0f **{ev['name']}** eventinin admini olarak atandiniz!\n\n"
        "Asagidaki checklist'i event gununue gecmeden tamamlayiniz.\n"
        "Event'e **2 gun** kaldiginda her **8 saatte bir** hatirlatma alacaksiniz.\n"
        "Her maddeye tiklayarak tamamlanmis olarak isaretleyebilirsiniz."
    )

    try:
        await user.send(dm_text, embed=embed, view=cl_view)
        await interaction.response.send_message(
            f"\u2705 {user.mention} **{ev['name']}** eventine admin atandi. "
            "Checklist DM olarak gonderildi.",
            ephemeral=True,
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            f"\u26a0\ufe0f {user.mention} admin atandi ancak DM'leri kapali \u2014 checklist gonderilemedi.\n"
            "Kullaniciya DM'lerini acmasini soyleyin.",
            ephemeral=True,
        )

    if old_admin and old_admin != user.id:
        try:
            old_member = interaction.guild.get_member(old_admin) if interaction.guild else None
            if old_member:
                await old_member.send(
                    f"\u2139\ufe0f **{ev['name']}** eventi icin admin gorevinden alindınız. "
                    f"Yeni admin: **{user.display_name}**"
                )
        except Exception:
            pass

    log.info("Admin atandi: %s -> %s (%s)", event_id, user, user.id)


@cmd_admin.autocomplete("event_id")
async def autocomplete_event_id(interaction: discord.Interaction, current: str):
    q = current.lower()
    choices = [
        app_commands.Choice(name=f"{ev['name']}  [{eid}]", value=eid)
        for eid, ev in events_db.items()
        if q in eid or q in ev["name"].lower()
    ]
    return choices[:25]


# ---------------------------------------------------------------------------
# Hatirlatici Gorevi
# ---------------------------------------------------------------------------


@tasks.loop(minutes=30)
async def reminder_task():
    """Her 30 dakikada bir calisir; uygun eventler icin 8 saatlik araliklarla DM gonderir."""
    now = datetime.now()
    for eid, ev in list(events_db.items()):
        date     = ev.get("date")
        admin_id = ev.get("admin_id")
        if not date or not admin_id:
            continue

        # Hatirlatma penceresi: [event - 2 gun, event)
        if now < date - timedelta(days=2) or now >= date:
            continue

        # Son hatirlatmadan bu yana 8 saat gectiyse gonder
        last = ev.get("last_reminder")
        if last and (now - last).total_seconds() < 8 * 3600:
            continue

        cl      = ev.get("checklist", {})
        pending = [lbl for k, lbl in CHECKLIST_ITEMS if not cl.get(k)]
        if not pending:
            continue  # Hepsi tamamlandi, hatirlatma gerekmez

        ev["last_reminder"] = now
        save_data()

        # Admini bul
        guild = bot.get_guild(ev.get("guild_id", 0))
        admin = (guild.get_member(admin_id) if guild else None) or bot.get_user(admin_id)
        if not admin:
            log.warning("Admin bulunamadi (id=%s), event: %s", admin_id, eid)
            continue

        remaining = date - now
        days      = remaining.days
        hours     = remaining.seconds // 3600
        if days > 0:
            time_str = f"{days} gun {hours} saat"
        else:
            time_str = f"{hours} saat"

        lines = "\n".join(f"  \u2b1c {p}" for p in pending)

        try:
            await admin.send(
                f"\u23f0 **[Hatirlatici] {ev['name']}**\n"
                f"Event'e yaklasik **{time_str}** kaldi!\n\n"
                f"Henuz tamamlanmamis checklist maddeleri:\n{lines}\n\n"
                "Lutfen bu maddeleri en kisa surede tamamlayin! \U0001f64f"
            )
            log.info(
                "Hatirlatici gonderildi: event=%s admin=%s eksik=%d",
                eid, admin_id, len(pending),
            )
        except discord.Forbidden:
            log.warning("Hatirlatici gonderilemedi (DM kapali): admin_id=%s", admin_id)
        except Exception as exc:
            log.warning("Hatirlatici hatasi (admin_id=%s): %s", admin_id, exc)


@reminder_task.before_loop
async def before_reminder():
    await bot.wait_until_ready()


# ---------------------------------------------------------------------------
# Giris Noktasi
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit(
            "\u274c DISCORD_TOKEN ortam degiskeni ayarlanmamis!\n"
            ".env dosyanizi olusturun ve DISCORD_TOKEN degerini girin."
        )
    bot.run(TOKEN, log_handler=None)
