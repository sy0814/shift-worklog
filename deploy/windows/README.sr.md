# Radni dnevnik · Uputstvo za instalaciju na Windows (za početnike)

**Jezik / 语言 / Language:** [中文](README.md) · Srpski · [English](README.en.md)

Ovo uputstvo vas korak po korak vodi kroz instalaciju sistema „Radni dnevnik” na Windows računar, tako da ga mogu koristiti svi telefoni i računari u pogonu. **Nije potrebno znanje programiranja.** Za svaki korak piše kako da proverite da je uspeo. Ako provera ne uspe, ne idite dalje.

> Potrebno vreme: prvi put **1–2 sata** (najviše se čeka na preuzimanje i instalaciju).

> **O kineskom tekstu na ekranu:** skripta za instalaciju ispisuje poruke na kineskom. Svako pitanje koje postavlja navedeno je i objašnjeno u [odeljku 6.3](#63-odgovorite-na-pitanja-skripte), pa ne morate znati kineski.

> **Nazivi menija u Windows-u:** pošto Windows može biti na engleskom ili srpskom, nazivi menija su dati na engleskom pod navodnicima, npr. „Settings” (Podešavanja).

---

## Sadržaj

1. [Nekoliko pojmova](#1-nekoliko-pojmova)
2. [Šta je potrebno pre početka](#2-šta-je-potrebno-pre-početka)
3. [Korak 1: Priprema serverskog računara](#3-korak-1-priprema-serverskog-računara)
4. [Korak 2: Instalacija baze podataka PostgreSQL](#4-korak-2-instalacija-baze-podataka-postgresql)
5. [Korak 3: Preuzimanje programa](#5-korak-3-preuzimanje-programa)
6. [Korak 4: Pokretanje skripte za instalaciju](#6-korak-4-pokretanje-skripte-za-instalaciju)
7. [Korak 5: Prva prijava i podešavanje na serverskom računaru](#7-korak-5-prva-prijava-i-podešavanje-na-serverskom-računaru)
8. [Korak 6: Podešavanje telefona](#8-korak-6-podešavanje-telefona)
9. [Svakodnevno održavanje](#9-svakodnevno-održavanje)
10. [Rezervne kopije i vraćanje podataka](#10-rezervne-kopije-i-vraćanje-podataka)
11. [Česti problemi](#11-česti-problemi)
12. [Prilog: gde se šta nalazi](#12-prilog-gde-se-šta-nalazi)

---

## 1. Nekoliko pojmova

| Pojam | Šta znači |
|---|---|
| **Serverski računar** | Windows računar na kome radi sistem. Mora stalno da bude uključen; svi telefoni i računari se povezuju na njega. |
| **IP adresa** | „Kućni broj” serverskog računara u mreži pogona, npr. `192.168.1.50`. Telefoni po toj adresi pronalaze sistem. |
| **Fiksna IP adresa** | Da se taj kućni broj nikada ne menja. Ako se promeni, telefoni više ne mogu da nađu sistem. |
| **Portovi 80 / 443** | Dva „ulaza” za veb stranice: 80 za obične, 443 za šifrovane (HTTPS). Nijedan drugi program ne sme da ih koristi. |
| **HTTPS i sertifikat** | HTTPS je šifrovana veza. Svaki telefon jednom instalira „sertifikat” ovog sistema da bi mu verovao; inače pregledač prikazuje „Nije bezbedno”. |
| **PowerShell** | Komandni prozor ugrađen u Windows. Koristimo ga za pokretanje skripte za instalaciju. |
| **Pokretanje kao administrator** | Pokretanje programa sa punim pravima u Windows-u. Potrebno za instalaciju programa i servisa. |
| **Servis** | Program koji radi u pozadini i sam se pokreće kada se računar uključi. |
| **PostgreSQL** | Program baze podataka u kome se čuvaju svi zapisi. |
| **DeepSeek API ključ** | Tajni ključ pomoću kog sistem koristi DeepSeek za prevod (kineski/srpski/engleski) i AI analizu. Sistem radi i bez njega, ali tekstovi se neće automatski prevoditi. |

---

## 2. Šta je potrebno pre početka

Proverite svaku stavku:

- [ ] **Računar sa Windows 10 ili Windows 11**, 64-bitni, najmanje 8 GB RAM-a i 50 GB slobodnog prostora na disku. Bolje je povezati ga kablom.
- [ ] Računar može **stalno da bude uključen** (bez gašenja i bez režima spavanja).
- [ ] Znate lozinku **administratorskog naloga** na tom računaru.
- [ ] Računar **ima pristup internetu** (može da otvori https://www.google.com). Potrebno je za preuzimanje programa tokom instalacije i kasnije za prevod.
- [ ] Telefoni na Wi-Fi mreži pogona mogu da pristupe tom računaru (obično važi u istoj mreži pogona; ako niste sigurni, pitajte mrežnog administratora).
- [ ] Možete da se prijavite na GitHub i preuzmete sistem (repozitorijum je privatan, vlasnik mora da vam da pristup), **ili** vam neko donese program na USB-u.
- [ ] (Opciono) DeepSeek API ključ. Može se uneti i kasnije na veb stranici.
- [ ] (Preporučeno) USB ili drugi disk za rezervne kopije.

---

## 3. Korak 1: Priprema serverskog računara

### 3.1 Pronađite IP adresu računara

1. Pritisnite **Win + R**, ukucajte `cmd` i pritisnite Enter. Otvoriće se crni prozor.
2. Ukucajte `ipconfig` i pritisnite Enter.
3. Pronađite mrežni adapter koji se koristi („Ethernet” za kabl, „Wi-Fi”/„WLAN” za bežičnu mrežu) i red **IPv4 Address**, npr. `192.168.1.50`.
4. **Zapišite ovu adresu.** Trebaće vam više puta.

### 3.2 Neka IP adresa bude fiksna (važno)

Ako se IP adresa promeni, svi telefoni gube vezu. Izaberite jedan način:

- **Način A (preporučeno): zamolite mrežnog administratora da u ruteru „rezerviše” ovu IP adresu za ovaj računar** (DHCP rezervacija). Dajte mu ime računara i adresu koju ste našli.
- **Način B: sami podesite statičku IP adresu.** Ne preporučuje se ako ne poznajete mreže, jer greška može da isključi računar iz mreže. Ako baš morate: „Settings” → „Network & internet” → „Ethernet” → „IP assignment” → „Edit” → „Manual” → uključite IPv4, pa unesite IP adresu, dužinu prefiksa podmreže (obično 24), mrežni prolaz (gateway) i DNS (te vrednosti dobijate od mrežnog administratora).

### 3.3 Proverite da su portovi 80 i 443 slobodni

Na većini računara ovo se može preskočiti. Samo računari sa programima za veb sajtove (npr. IIS) mogu da zauzimaju ove portove. Skripta to sama proverava i javlja koji program ih koristi.

Ako je u pitanju IIS: „Control Panel” → „Programs” → „Turn Windows features on or off” → isključite „Internet Information Services” → OK → ponovo pokrenite računar kada se zatraži.

### 3.4 O režimu spavanja

Skripta sama isključuje „spavanje kada je računar na struji”. Ako je u pitanju laptop, neka stalno bude na punjaču i **ne zatvarajte poklopac** (ili u podešavanjima napajanja za „When I close the lid” izaberite „Do nothing”).

---

## 4. Korak 2: Instalacija baze podataka PostgreSQL

1. U pregledaču otvorite <https://www.enterprisedb.com/downloads/postgres-postgresql-downloads>.
2. U redu **PostgreSQL 17** kliknite dugme za preuzimanje ispod **Windows x86-64**. Fajl se zove otprilike `postgresql-17.x-windows-x64.exe`.
3. Dvaput kliknite na fajl. Ako Windows pita „Do you want to allow this app to make changes to your device?”, kliknite **Yes**.
4. U programu za instalaciju izaberite:

| Stranica instalacije | Šta uraditi |
|---|---|
| Setup (dobrodošlica) | Kliknite **Next** |
| Installation Directory | Ostavite kako jeste, **Next** |
| Select Components | Ostavite kako jeste, **Next** (Stack Builder možete isključiti, nije potreban) |
| Data Directory | Ostavite kako jeste, **Next** |
| **Password** | **Izaberite lozinku za korisnika `postgres` i unesite je dvaput. Nemojte je zaboraviti!** Skripta za instalaciju će je tražiti. Zapišite je na papir i predajte odgovornoj osobi. |
| Port | Ostavite **5432**, **Next** |
| Advanced Options | Ostavite „Default locale”, **Next** |
| Pre Installation Summary | **Next** |
| Ready to Install | **Next**, sačekajte nekoliko minuta |
| Completing | **Isključite** „Launch Stack Builder at exit”, kliknite **Finish** |

**Kako proveriti:** pritisnite Win + R, ukucajte `services.msc` i Enter. Na spisku treba da postoji **postgresql-x64-17** sa statusom „Running”.

---

## 5. Korak 3: Preuzimanje programa

**Sa GitHub-a:**

1. U pregledaču se prijavite na GitHub i otvorite stranicu repozitorijuma sistema (adresu dobijate od odgovorne osobe).
2. Kliknite zeleno dugme **Code** → **Download ZIP**.
3. U fascikli „Downloads” **desni klik na ZIP → „Extract All”** i raspakujte u `D:\shift-worklog` (ako nema diska D:, koristite `C:\shift-worklog`).

**Sa USB-a:** kopirajte celu fasciklu programa u `D:\shift-worklog`.

**Kako proveriti:** otvorite `D:\shift-worklog`. Treba odmah da vidite fascikle `backend`, `frontend` i `deploy`.

> Napomena: ponekad raspakivanje doda još jedan nivo fascikle, npr. `D:\shift-worklog\shift-worklog-master\backend`. To nije problem; u komandama ispod samo koristite stvarnu putanju.

---

## 6. Korak 4: Pokretanje skripte za instalaciju

### 6.1 Otvorite PowerShell kao administrator

- **Windows 11:** desni klik na dugme **Start** → **„Terminal (Admin)”**.
- **Windows 10:** desni klik na dugme **Start** → **„Windows PowerShell (Admin)”**.

Ako Windows traži dozvolu, kliknite **Yes**. U naslovu prozora treba da piše „Administrator”.

### 6.2 Ukucajte komande

Ukucajte sledeće komande **jednu po jednu** i posle svake pritisnite Enter. Možete ih kopirati i nalepiti: desni klik u prozoru PowerShell-a lepi tekst.

Prva komanda dozvoljava ovom prozoru da pokreće skripte (važi samo za ovaj prozor, posle zatvaranja se vraća):

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
```

Druga komanda vas vodi u fasciklu programa (promenite putanju prema mestu gde ste raspakovali):

```powershell
cd D:\shift-worklog\deploy\windows
```

Treća komanda pokreće instalaciju:

```powershell
.\install.ps1
```

### 6.3 Odgovorite na pitanja skripte

Skripta prikazuje devet koraka, od „==> 1/9 …” do „==> 9/9 …”, i postavlja nekoliko pitanja. **Pitanja su na kineskom**; evo šta znače:

| Tekst na ekranu (kineski) | Značenje | Šta uneti |
|---|---|---|
| 手机用哪个地址访问？直接回车 = 用上面检测到的 | Koju adresu će telefoni koristiti? Enter = pronađena adresa. | Pogledajte red iznad, posle „检测到：” (pronađeno:). Ako sadrži IP adresu iz koraka 3.1, **samo pritisnite Enter**. Inače ukucajte IP, npr. `192.168.1.50`. |
| 请输入安装 PostgreSQL 时设置的 postgres 密码 | Unesite lozinku za `postgres` koju ste izabrali pri instalaciji PostgreSQL-a. | Lozinka iz koraka 2. **Dok kucate, prikazuju se samo `*`; to je normalno.** |
| 设置系统管理员 admin 的登录密码（至少 8 位） | Izaberite lozinku za administratora `admin` na veb stranici (najmanje 8 znakova). | Izaberite lozinku od **8 ili više znakova** i zapišite je. Ako je kraća, skripta će pitati ponovo. |
| DeepSeek API Key（可以先直接回车……） | DeepSeek API ključ (možete pritisnuti Enter i uneti ga kasnije na veb stranici). | Nalepite ključ ako ga imate, inače **samo pritisnite Enter**. |
| 备份放哪里？…… | Gde čuvati rezervne kopije? | Ako imate drugi disk, ukucajte npr. `D:\WorkRecordBackup`. Inače samo Enter (kopije idu u `C:\WorkRecord\backups`). |

Pri prvom pokretanju skripta sama preuzima i instalira Python, Node.js i druge programe, što **može trajati 10–30 minuta**. Normalno je da se duže vreme ništa novo ne pojavljuje. Ne zatvarajte prozor.

### 6.4 Kako proveriti da je uspelo

Na kraju se pojavljuje zeleno **„安装完成！”** (Instalacija završena!) i otprilike:

```
安装完成！
  手机 / 电脑先打开   http://192.168.1.50/install   安装证书（只需一次）
  然后访问           https://192.168.1.50
  管理员账号         admin（密码是刚才设置的）
```

Značenje:
- **Prvo** na telefonima i računarima otvorite `http://192.168.1.50/install` i instalirajte sertifikat (samo jednom).
- **Zatim** koristite `https://192.168.1.50`.
- **Administratorski nalog:** `admin`, sa lozinkom koju ste upravo izabrali.

**Napravite snimak ekrana (screenshot) ovog dela.**

### 6.5 Ako se pojavi crvena greška

- Skripta se zaustavlja i (na kineskom) objašnjava koji korak nije uspeo i zašto; obično piše i šta treba uraditi.
- Kada to rešite, **samo ponovo pokrenite `.\install.ps1`.** Završeni koraci se preskaču, a već unete lozinke se ne traže ponovo.
- Ako ne znate šta da radite, **napravite snimak celog prozora** i pošaljite ga tehničkoj osobi za kontakt.

---

## 7. Korak 5: Prva prijava i podešavanje na serverskom računaru

### 7.1 Instalirajte sertifikat na serverski računar

1. Na serverskom računaru u Edge-u ili Chrome-u otvorite `http://VAŠA-IP/install` (npr. `http://192.168.1.50/install`).
2. Kliknite **① Preuzmi sertifikat** i preuzmite `workrecord-ca.crt`.
3. Dvaput kliknite na fajl → „Install Certificate” → „Local Machine” → Next → „Place all certificates in the following store” → Browse → „Trusted Root Certification Authorities” → OK → Next → Finish.
4. **Potpuno zatvorite pregledač i ponovo ga otvorite.**

> Savet: na samom serverskom računaru možete otvoriti i `http://127.0.0.1:8000`, za šta nije potreban sertifikat. Radi samo na tom računaru i korisno je kada se traži uzrok problema.

### 7.2 Prijava

Otvorite `https://VAŠA-IP`. U adresnoj traci treba da se vidi katanac, bez upozorenja „Nije bezbedno”. Prijavite se kao **admin** sa vašom lozinkom.

Jezik se menja gore desno (中文 / Srpski / English).

### 7.3 Podešavanja koja prvo treba uraditi

Posle prijave otvorite meni **Upravljanje** gore i uradite redom:

1. **Raspored → Ekipe:** nova instalacija **nema ekipa ni naloga šefova smena**; dodajte ih sami.
   - Kliknite „Nova ekipa”: za smenske ekipe 1–4 koristite „Brzo → Četiri ekipe (8 dana)”, označite „Glavna ekipa” i podesite „Prvi dan ciklusa”; za dnevnu smenu „Pon–pet prva smena” i označite „Praznicima slobodno”.
   - Zatim uporedite „Kalendar smena” sa fabričkom tabelom prisustva (treća smena se računa na dan kada se završava: „3” = od 23:00 prethodnog dana do 07:00). Državne praznike unesite u „Praznici / radne subote”.
2. **Radnici:** kliknite „Dodaj više”, izaberite ekipu, nalepite jedno ime po redu i sačuvajte. Uradite to za svaku ekipu.
   - Unesite **matični broj** (Sap No. iz tabele prisustva): koristi se za uvoz prisustva i za prijavu.
   - U koloni „Uloga” izaberite pravu ulogu za šefove i zamenike. Dodavanjem osobe **nalog se otvara automatski**: šefovi se prijavljuju korisničkim imenom + lozinkom, korisničko ime je matični broj (radi i jedno i drugo); članovi koriste „Lični nalog” (ekipa → svoja slika → lična lozinka). Lozinka je „Podešavanja → Podrazumevana lozinka za nove radnike” (podrazumevano `123456`) i **mora se promeniti pri prvoj prijavi**.
   - Šta koja uloga sme podešava se u „Upravljanje → Uloge i prava”. „Upravljanje → Nalozi” služi samo za nove administratorske naloge.
3. **Podešavanja → Podrazumevana lozinka za nove radnike:** promenite `123456` pre dodavanja ljudi.
4. **Podešavanja:**
   - Ako DeepSeek ključ niste uneli tokom instalacije, unesite ga u polje „API ključ”, kliknite „**Testiraj vezu**”, i kada se pojavi zeleno „Veza radi” sa primerima prevoda, kliknite „**Sačuvaj**”.
   - U „Podešavanju upozorenja” možete promeniti posle koliko sati se nezavršen zadatak označava crveno.
5. **Rečnik:** već sadrži 51 stručni izraz iz prerade rude i elektrotehnike. **Molimo srpske kolege da provere srpske prevode:** „Izvezi CSV”, ispravite u Excel-u, zatim „Uvezi CSV”.

---

## 8. Korak 6: Podešavanje telefona

Svaki telefon ovo radi samo jednom. Ovaj odeljak možete odštampati za šefove smena. Stranica `http://VAŠA-IP/install` na telefonu prikazuje ista uputstva na kineskom, srpskom i engleskom.

### 8.1 Android

1. Povežite telefon na Wi-Fi mrežu pogona.
2. U **Chrome-u** otvorite `http://VAŠA-IP/install` i dodirnite **① Preuzmi sertifikat**.
3. Otvorite **Podešavanja** i potražite „**sertifikat**” (ili „certificate”). Pronađite „**Instaliraj sertifikat**” ili „**CA sertifikat**”. Mesto zavisi od proizvođača; često je: Podešavanja → Bezbednost → Još podešavanja bezbednosti → Šifrovanje i akreditivi → Instaliraj sertifikat → CA sertifikat.
4. Ako telefon upozori, dodirnite „**Ipak instaliraj**” i izaberite preuzeti `workrecord-ca.crt`.
5. Vratite se u Chrome, otvorite `https://VAŠA-IP` i prijavite se nalogom šefa smene.
6. Dodirnite **⋮** gore desno u Chrome-u → **Dodaj na početni ekran** → Dodaj. Od sada sistem otvarate preko ikone na početnom ekranu.

### 8.2 iPhone / iPad

1. Povežite se na Wi-Fi mrežu pogona.
2. **Obavezno koristite Safari** (ne drugi pregledač ni aplikaciju). Otvorite `http://VAŠA-IP/install`, dodirnite **① Preuzmi sertifikat**, zatim „**Dozvoli**”.
3. Otvorite **Podešavanja**. Pri vrhu se pojavljuje „**Profil preuzet**”; dodirnite ga → **Instaliraj** (gore desno) → unesite šifru telefona → ponovo **Instaliraj**.
   - Ako ga ne vidite: Podešavanja → Opšte → **VPN i upravljanje uređajem**.
4. **Ovaj korak se najčešće zaboravi:** Podešavanja → Opšte → **O uređaju** → skroz dole → **Podešavanja poverenja sertifikata** → **uključite prekidač** pored sertifikata ovog sistema → Nastavi.
5. U Safariju otvorite `https://VAŠA-IP` i prijavite se.
6. Dodirnite dugme **Deli** u Safariju (kvadrat sa strelicom) → **Dodaj na početni ekran** → Dodaj.

### 8.3 Dobro je znati

- Stranice koje ste jednom otvorili dok ste bili na mreži **otvaraju se i bez signala**, sa podacima od poslednje veze. Gore se pojavljuje žuta traka „Van mreže”.
- Zadaci i slike napravljeni bez signala čuvaju se na telefonu („Čeka sinhronizaciju” gore desno) i **automatski se šalju** kada se veza vrati.
- Posle ažuriranja sistema telefon prikazuje „Nova verzija”; dodirnite „Osveži”.

---

## 9. Svakodnevno održavanje

### 9.1 Sistem radi u pozadini

Postoje dva servisa. **Sami se pokreću kada se računar uključi** i sami se ponovo pokreću posle greške. Obično ne treba ništa da radite.

| Naziv servisa | Namena |
|---|---|
| WorkRecord App | Sam sistem |
| WorkRecord HTTPS (Caddy) | Šifrovani ulaz i stranica za preuzimanje sertifikata |

**Provera:** Win + R, ukucajte `services.msc`, Enter, pronađite ta dva servisa. Status treba da bude „Running”. Po potrebi: desni klik → „Restart”.

### 9.2 Ako se sistem ne otvara (proverite ovim redom)

1. Da li je serverski računar **uključen**, nije u režimu spavanja i povezan je na mrežu?
2. Na serverskom računaru otvorite `http://127.0.0.1:8000`:
   - **Otvara se:** sistem radi, problem je u mreži, HTTPS-u ili sertifikatu na telefonu. Pogledajte [Česte probleme](#11-česti-problemi).
   - **Ne otvara se:** u `services.msc` ponovo pokrenite „WorkRecord App”, sačekajte 1 minut i pokušajte ponovo.
3. I dalje ne radi: otvorite `C:\WorkRecord\logs` i pošaljite fajl `WorkRecordApp.err.log` tehničkoj osobi za kontakt.

### 9.3 Prelazak na novu verziju

**Najlakše: automatsko preuzimanje i ažuriranje** (server mora imati internet). Otvorite PowerShell kao administrator (vidi 6.1) i ukucajte, jednu po jednu:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
```

```powershell
C:\WorkRecord\app\deploy\windows\update.ps1 -Online
```

Skripta sama preuzima najnoviju verziju sa GitHub-a i zatim ažurira kao u tačkama 3 i 4 ispod. Sačekajte poruku 「更新完成」 („ažuriranje završeno”).
(Pre prvog korišćenja `-Online` instaliranu verziju treba jednom ažurirati ručno kao ispod – starije verzije nemaju ovu opciju.)

**Ručno preuzimanje:**

1. Preuzmite novu verziju kao u koraku 3 i raspakujte je u **novu fasciklu**, npr. `D:\shift-worklog-new`.
2. Otvorite PowerShell kao administrator (vidi 6.1) i ukucajte, jednu po jednu:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
```

```powershell
cd D:\shift-worklog-new\deploy\windows
```

```powershell
.\update.ps1
```

3. Skripta za ažuriranje **prvo pravi rezervnu kopiju**, zatim zaustavlja sistem, ažurira program, nadograđuje bazu i sve ponovo pokreće. Kada se pojavi „更新完成” (ažuriranje završeno), gotovo je. Sistem nije dostupan nekoliko minuta, **zato ažurirajte van vremena primopredaje smena**.
4. Podaci, slike, lozinke i sertifikati ostaju, i telefonima ne treba novi sertifikat.

### 9.4 Promena IP adrese servera

Promena adrese ima dva dela: prvo računar mora **zaista da dobije novu IP adresu**, zatim sistemu kažete koja je nova adresa.

**① Dodelite računaru novu IP adresu:** zamolite mrežnog administratora da promeni rezervaciju u ruteru, ili podesite statičku adresu kao u 3.2. Zatim u `cmd` pokrenite `ipconfig` i proverite da „IPv4 Address” pokazuje novu adresu.

**② Recite sistemu novu adresu** (izaberite jedno):

**Način 0: na veb stranici (najlakše).** U „Podešavanja → Adresa pristupa” upišite novu adresu, kliknite „Sačuvaj i primeni” i posle oko 10 sekundi otvorite novu adresu. Pazite na redosled:
- IP još nije promenjen: prvo upišite obe adrese „stara, nova” i sačuvajte; zatim uradite ①; na kraju obrišite staru adresu.
- IP je već promenjen (stara adresa ne radi): na **samom serverskom računaru** otvorite `http://127.0.0.1:8000`, prijavite se kao administrator i promenite ovde.
- Stranica prikazuje trenutne IP adrese servera; kliknite jednu da se upiše.

**Način A: skripta za adresu (preporučeno).** U PowerShell-u kao administrator ukucajte jednu po jednu, sa vašom novom IP adresom u poslednjem redu:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
```

```powershell
cd C:\WorkRecord\app\deploy\windows
```

```powershell
.\set-address.ps1 192.168.1.60
```

> Ako u `C:\WorkRecord\app\deploy\windows` nema fajla `set-address.ps1` (instalacije pre 23.11.2026. ga nemaju), prvo preuzmite i raspakujte najnoviju verziju, pa iste komande pokrenite u fascikli `deploy\windows` **novog preuzimanja**.

Da biste pristupali i preko imena računara, odvojite zarezom i stavite navodnike: `.\set-address.ps1 '192.168.1.60, worklog-server'`

Kada se pojavi zeleno „地址已修改。” (adresa je promenjena), gotovo je.

**Način B: ručno u Notepad-u (ne treba ništa preuzimati).**

1. Otvorite Notepad kao administrator: u Start meniju potražite „Notepad” → desni klik → „Run as administrator”.
2. U Notepad-u: „File” → „Open”, za tip fajla izaberite „All files” i otvorite `C:\WorkRecord\tools\WorkRecordCaddy.xml`.
3. Pronađite ovaj red, zamenite staru IP adresu unutar `value="..."` novom i sačuvajte:

```
<env name="SITE_HOSTS" value="192.168.1.50"/>
```

4. Pritisnite Win + R, ukucajte `services.msc`, Enter, pronađite „WorkRecord HTTPS (Caddy)”, desni klik → „Restart”.

**③ Posle promene**

- Podaci i lozinke ostaju. **Telefoni koji već imaju sertifikat ne treba ponovo da ga instaliraju**; samo otvorite `https://NOVA-IP`.
- Stare ikone na početnom ekranu vode na staru adresu i više se ne otvaraju: otvorite novu adresu, ponovo „Dodaj na početni ekran” i obrišite staru ikonu.
- Novi telefoni kao i obično instaliraju sertifikat sa `http://NOVA-IP/install`.

### 9.5 Čuvar (automatska upozorenja)

Skripta za instalaciju / ažuriranje pravi zakazani zadatak **WorkRecordWatchdog** koji na svakih 5 minuta proverava:

| Šta proverava | Kad postoji problem |
|---|---|
| Da li baza (PostgreSQL) i oba servisa rade | Automatski ih pokreće; javi jednom i kad je ponovno pokretanje uspelo (sa poslednjom greškom iz loga pre zaustavljanja), a ako nije uspelo upozori i navede **moguće uzroke** koje je pronašao |
| Da li sistem odgovara | Servis radi, ali sistem ne odgovara: upozorenje |
| Rezervna kopija | Kopija nije uspela ili više od 26 sati nema uspešne kopije: upozorenje |
| Prostor na disku | Manje od 5 GB ili 10% slobodno na disku sa podacima programa ili sa kopijama: upozorenje |

- **Kako upozorava**: **iskačući prozor na serverskom računaru** (svima koji su prijavljeni), plus Windows **dnevnik događaja** (Event Viewer → Windows Logs → Application, izvor `WorkRecord`) i `C:\WorkRecord\logs\watchdog.log`. Neka na serveru uvek neko bude prijavljen, da bi se prozor video.
- Kad servis ne može da se pokrene, upozorenje navodi „可能原因 (mogući uzroci): 1) …; 2) …“. Čuvar sam proverava: servis podešen na „Disabled“ (onemogućen), grešku koju je Windows vratio pri pokretanju, nedostaju programske datoteke (npr. PostgreSQL deinstaliran do pola), nedostaje direktorijum sa podacima, port zauzima drugi program (5432 / 8000 / 80 / 443), nedostaje Python, `.venv`, `.env` ili `caddy.exe`, pun disk, servis od kog zavisi ne radi, poslednja greška u logu i greška servisa koju je Windows zabeležio. Uz svaki uzrok piše šta da uradite. Upozorenje o neuspeloj kopiji objašnjava i izlazni kod (npr. `-1073741515` = programu nedostaje DLL, instalacija je nepotpuna).
- **Jezik upozorenja**: podrazumevano kineski. Za srpski ili engleski na veb stranici u „Sistemska podešavanja → Skladište i rezervne kopije → Jezik upozorenja na serveru“ izaberite „Srpski“ ili „English“ i sačuvajte. Važi od sledeće provere (u roku od 5 minuta); ponovno pokretanje nije potrebno. Tekstovi grešaka koje daje sam Windows (uzrok „Greška koju je zabeležio Windows“) su na jeziku Windows-a i ne mogu da se prevedu.
- Isti problem iskače **najviše jednom u 60 minuta**; kad se reši, dobijete još jednu poruku da je otklonjen.
- Neuspela kopija i pun disk se **prikazuju i kao crveno obaveštenje na početnoj strani** kad se administrator prijavi.
- Tokom ažuriranja skripta pauzira čuvara i na kraju ga ponovo uključi. **Ako ažuriranje pukne na pola, čuvar ostaje pauziran**: rešite problem i ponovo pokrenite `update.ps1`.
- Windows Home nema program za iskačuće prozore (msg.exe): tamo dobijate samo dnevnik događaja i log fajl.

Poruke u prozoru su na kineskom:

| Tekst u prozoru (početak) | Značenje |
|---|---|
| 服务 … 停了，已自动重新启动 | Servis je stao i automatski je ponovo pokrenut |
| 服务 … 停了，自动启动失败 | Servis je stao i ne može da se pokrene – pokrenite ga u Services i pogledajte log |
| … 在运行，但系统没有响应 | Servis radi, ali sistem ne odgovara – pogledajte log, restartujte servis |
| 备份失败 | Rezervna kopija nije uspela – pogledajte `logs\backup.log` |
| 超过 26 小时没有成功的备份 | Više od 26 sati nema uspešne kopije – proverite zadatak WorkRecordBackup |
| 磁盘 …: 快满了 | Taj disk je skoro pun |
| 已恢复 | Problem je otklonjen |

---

## 10. Rezervne kopije i vraćanje podataka

### 10.1 Automatske rezervne kopije

Svake noći u **03:40** pravi se kopija u fasciklu izabranu tokom instalacije (podrazumevano `C:\WorkRecord\backups`):

| Fascikla | Sadržaj |
|---|---|
| `db` | Baza podataka, fajlovi tipa `workrecord-20261122-0340.dump`, **čuvaju se 30 dana** |
| `uploads` | Slike uz zadatke |
| `caddy-pki` | HTTPS sertifikat. Ako se izgubi, svi telefoni moraju ponovo da instaliraju sertifikat. |
| `config` | Fajl sa podešavanjima. Sadrži lozinke, **zato ga ne delite.** |

**Proveravajte jednom nedeljno:** otvorite `C:\WorkRecord\logs\backup.log`; poslednji redovi treba da sadrže današnje „备份完成” (kopija završena).

**Napravite kopiju i na drugom mestu** (USB, drugi računar, mrežni disk). Ako je kopija na istom disku kao server, kvar diska uništava oboje.

**Podešavanje na veb-stranici (preporučeno):** administrator → „管理 → 系统设置 → 存储与备份” (Upravljanje → Podešavanja sistema → Skladište i rezervne kopije):

- **Lokacija kopije**: gde se čuva kopija (npr. `D:\WorkRecordBackup`); dugme „Proveri” pokazuje da li se može pisati i koliko je mesta slobodno.
- **Druga kopija**: posle svake kopije automatski još jedna ovde – USB / spoljni disk, deljeni folder na mreži ili **folder klijenta za oblak** (OneDrive i sl.; klijent ga sam šalje u oblak). Kopija sadrži lozinku baze, zato oblak mora biti privatan.
- Na stranici se vidi **poslednja kopija** (vreme, uspeh, veličina baze, slobodno mesto), a postoji i dugme „Napravi kopiju sada”.
- **Arhiviranje originalnih slika**: kad se uključi, originali stariji od N meseci se svaki dan u 02:50 premeštaju u „folder arhive” (drugi disk). Pregledne slike i sličice ostaju, sistem radi isto; „Original” se čita sa arhivskog diska, a ako nije priključen, prikazuje se pregledna slika.

### 10.2 Ručna rezervna kopija

U PowerShell-u kao administrator:

```powershell
powershell -ExecutionPolicy Bypass -File C:\WorkRecord\app\deploy\windows\backup.ps1
```

### 10.3 Vraćanje podataka (ako je baza oštećena ili posle velike greške)

> Vraćanje **zamenjuje** trenutne podatke podacima iz kopije. Sve što je uneto posle te kopije biće izgubljeno. Ako niste sigurni, pitajte tehničku osobu za kontakt.

1. Zaustavite sistem (PowerShell kao administrator):

(prvo pauzirajte čuvara, inače će ponovo pokrenuti servise usred vraćanja)

```powershell
Disable-ScheduledTask -TaskName WorkRecordWatchdog
```

```powershell
Stop-Service WorkRecordCaddy, WorkRecordApp
```

2. Pronađite lozinku baze: otvorite `C:\WorkRecord\app\backend\.env` u Notepad-u. U redu `DATABASE_URL=` lozinka je tekst između `workrecord:` i `@`.
3. Vratite bazu (zamenite lozinku i naziv fajla stvarnim vrednostima):

```powershell
$env:PGPASSWORD = 'LOZINKA-BAZE'
```

```powershell
& 'C:\Program Files\PostgreSQL\17\bin\pg_restore.exe' --clean --if-exists -h 127.0.0.1 -U workrecord -d workrecord 'C:\WorkRecord\backups\db\workrecord-20261122-0340.dump'
```

4. Vratite slike:

```powershell
robocopy C:\WorkRecord\backups\uploads C:\WorkRecord\data\uploads /E
```

5. Pokrenite sistem:

```powershell
Start-Service WorkRecordApp, WorkRecordCaddy
```

(zatim ponovo uključite čuvara)

```powershell
Enable-ScheduledTask -TaskName WorkRecordWatchdog
```

### 10.4 Prelazak na novi serverski računar

1. Na novom računaru instalirajte sve (koraci 1–4, uključujući PostgreSQL).
2. Kopirajte celu fasciklu rezervnih kopija sa starog računara i vratite bazu i slike kao u 10.3.
3. Vratite sertifikat i podešavanja, da **telefoni zadrže sertifikat i niko ne mora ponovo da se prijavljuje**:
   - Kopirajte sadržaj fascikle `caddy-pki` u `C:\WorkRecord\data\caddy\caddy\pki` (zamenite postojeće).
   - Kopirajte `config\backend.env` u `C:\WorkRecord\app\backend\.env` (zamenite postojeći).
4. Ponovo pokrenite oba servisa. Ako novi računar ima drugu IP adresu, uradite i korak 9.4.

---

## 11. Česti problemi

| Šta vidite | Uzrok i rešenje |
|---|---|
| Servis neće da se pokrene; `logs\WorkRecordApp.err.log` stalno prijavljuje grešku `10048` (svaka adresa soketa sme da se koristi samo jednom) | Port 8000 drži zaostali stari proces (starije verzije su ga mogle ostaviti pri zaustavljanju servisa). Pokrenite `update.ps1` jednom i problem je trajno rešen: zaustavljanje servisa više ne ostavlja proces, a čuvar i skripta za ažuriranje sami čiste zaostale procese. Brzo ručno rešenje: u administratorskom PowerShell-u pokrenite `Get-NetTCPConnection -LocalPort 8000 -State Listen` da dobijete broj procesa, proverite da je python, pokrenite `Stop-Process -Id <broj> -Force`, pa pokrenite servis. |
| Upozorenje „servis baze postgresql-… je stao“, uzrok „nedostaju programske datoteke PostgreSQL-a“, kopija ne uspeva sa izlaznim kodom `-1073741515` | PostgreSQL je deinstaliran do pola (ovo se stvarno desilo 2026-11). **Direktorijum sa podacima je obično i dalje tu, podaci nisu izgubljeni.** Prvo kopirajte ceo `C:\Program Files\PostgreSQL\<verzija>\data` na sigurno mesto; zatim preuzmite instalaciju **iste glavne verzije** i ponovo instalirajte, sa istim instalacionim direktorijumom i direktorijumom podataka i istom lozinkom za postgres; posle toga pokrenite servis baze i oba servisa i jednom ručno pokrenite `backup.ps1`. Ako nema ni direktorijuma sa podacima, uradite „10.3 Vraćanje podataka“ iznad. |
| „…cannot be loaded because running scripts is disabled on this system” | Niste prvo pokrenuli `Set-ExecutionPolicy -Scope Process Bypass -Force`, ili ste je pokrenuli u drugom prozoru. Pokrenite je prvo u istom prozoru. |
| Poruka „请右键以管理员身份运行 PowerShell” | „Pokrenite PowerShell kao administrator.” Otvorite ga ponovo kao u 6.1. |
| Poruka „没有找到 PostgreSQL” | „PostgreSQL nije pronađen.” Instalirajte ga (korak 2) na podrazumevano mesto. |
| Greška baze koja pominje lozinku postgres | Pogrešna lozinka. Ponovo pokrenite `.\install.ps1` i unesite je ponovo. Ako ste je zaboravili, ponovo instalirajte PostgreSQL (moguće samo dok još nema podataka). |
| Poruka „端口 80 / 443 已被程序……占用” | „Port 80/443 koristi program …”. Zaustavite taj program (vidi 3.3) i ponovo pokrenite skriptu. |
| Ne uspeva preuzimanje Python-a / Caddy-ja | Računar nema internet ili ga blokira firewall firme. Obratite se mrežnom administratoru. |
| Telefoni ne mogu da otvore `http://IP/install` | Telefon nije u istoj mreži, ili neki bezbednosni program na računaru blokira portove 80/443; dozvolite ih u tom programu. |
| Telefon prikazuje „Nije bezbedno” / „sertifikat nije važeći” | Sertifikat nije dobro instaliran. Na Android-u ga instalirajte ponovo. Na iPhone-u proverite da je prekidač iz koraka 8.2.4 (Podešavanja poverenja sertifikata) uključen. |
| „Sertifikat ne odgovara adresi” | Koristili ste adresu koja nije uneta tokom instalacije (npr. ime računara). Koristite adresu prikazanu na kraju instalacije, ili je dodajte kao u 9.4. |
| Zadaci stalno „Čeka prevod” | Server nema internet ili DeepSeek ključ nije unet. U „Podešavanjima” kliknite „Testiraj vezu”. |
| Ne otvara se posle ponovnog pokretanja računara | Servisima treba 1–2 minuta da se pokrenu. Sačekajte, pa proverite kao u 9.2. |
| Zaboravljena lozinka za admin | U `C:\WorkRecord\app\backend\.env` red `ADMIN_PASSWORD=` sadrži lozinku iz **prve instalacije**. Ako je kasnije promenjena na veb stranici, obratite se tehničkoj osobi za kontakt. |

---

## 12. Prilog: gde se šta nalazi

| Lokacija | Sadržaj |
|---|---|
| `C:\WorkRecord\app` | Program (zamenjuje se pri ažuriranju) |
| `C:\WorkRecord\app\backend\.env` | Podešavanja: lozinka baze, ključevi. **Ne brisati i ne deliti.** |
| `C:\WorkRecord\data\uploads` | Slike uz zadatke |
| `C:\WorkRecord\data\caddy` | HTTPS sertifikat |
| `C:\WorkRecord\logs` | Dnevnici rada programa i rezervnih kopija |
| `C:\WorkRecord\backups` | Podrazumevano mesto za rezervne kopije |
| `C:\WorkRecord\tools` | Pomoćni programi (Caddy, upravljanje servisima) |

**Deinstalacija** (retko potrebna). U PowerShell-u kao administrator pokrenite komandu ispod. Podrazumevano uklanja samo servise; podaci i baza ostaju.

```powershell
powershell -ExecutionPolicy Bypass -File C:\WorkRecord\app\deploy\windows\uninstall.ps1
```
