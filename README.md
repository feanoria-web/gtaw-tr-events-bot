# GTAW:TR Events Team Discord Botu

## Kurulum

1. **Gereksinimler**
   ```
   pip install -r requirements.txt
   ```

2. **`.env` dosyasi olustur**
   ```
   cp .env.example .env
   ```
   Icini doldur:
   - `DISCORD_TOKEN`: Discord Developer Portal'dan alinacak bot tokeni
   - `EVENTS_TEAM_ROLE_ID`: Events Team rolunun ID'si (Sage Mode'da tikla > ID Kopyala)

3. **Botu calistir**
   ```
   python bot.py
   ```

## Komutlar

| Komut | Aciklama |
|-------|----------|
| `/event create <name> <date> [description]` | Event olusturur, Events Team etiketler, Katil butonu ekler |
| `/event admin <event_id> <user>` | Kullaniciya event adminligi verir, checklist DM'ler |

### Tarih formatlari
- `25/07/2025 20:00`
- `25.07.2025 20:00`
- `25/07/2025` (saat belirtilmezse 00:00)

## Nasil Calisir?

### Event Olusturma
`/event create name:"Yaz Festivali" date:"25/07/2025 20:00" description:"Buyuk yaz etkinligi"`

Bot:
- Events Team rolunu etiketler
- Embed duyuru gonderir (tarih + event ID gosterir)
- "Katil / Hak Talep Et" butonu ekler

### Katilma Butonu
Tiklayanin karsisina ephemeral (sadece kendisi gorebilir) bir menu acar:
- NC Hakki Istiyorum
- +1 Karakter Slotu Istiyorum

Secimden sonra uyari mesaji gosterilir ve event adminine DM gider.

### Admin Atama
`/event admin event_id:"yaz_festivali" user:@Kullanici`

- Event ID'si otomatik tamamlama ile secilebilir
- Kullaniciya DM olarak checklist gonderilir:
  - [ ] Feanor'un onayi alindi
  - [ ] LFM'in tam onayi alindi
  - [ ] Ilgili olusumun detayli plandan haberi var
  - [ ] Management onayi alindi (buyuk kapsamli eventler icin)
- Checklist butona tiklayarak isaretlenir

### Hatirlatici Sistemi
Event tarihinden **2 gun once** baslar, **8 saatte bir** adminin DM'ine gider.
Tamamlanmamis maddeler listelenir. Hepsi tamamlandiysa hatirlatma durur.

## Discord Bot Izinleri
Bot'a su izinleri verin:
- `Send Messages`
- `Embed Links`
- `Use Slash Commands`
- `Mention Everyone` (rol etiketi icin)

Intents (Developer Portal > Bot > Privileged Gateway Intents):
- `SERVER MEMBERS INTENT` - aktif
- `MESSAGE CONTENT INTENT` - aktif
