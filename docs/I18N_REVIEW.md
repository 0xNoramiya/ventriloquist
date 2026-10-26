# Indonesian strings for review

Rifqi: please check these patient-facing Indonesian strings. `{hon}` becomes Bapak, Ibu or Anda from
the profile. They live in `backend/app/engine/taxonomy_v1.yaml` (messages and questions),
`backend/app/engine/spelling.py` (spelling prompts), `backend/app/sessions/session.py` (alarm and
pause texts) and `frontend/src/i18n/id.json` (screens).

## Messages (spoken aloud in first person)

| id | English | Indonesian |
|---|---|---|
| pain | I'm in pain. | Saya kesakitan. |
| breathing | It's hard to breathe. | Saya sulit bernapas. |
| suction | There's mucus in my throat. I need suction. | Ada lendir di tenggorokan, tolong disedot. |
| tube_discomfort | The tube or tape is bothering me. | Selang atau plesternya mengganggu. |
| thirst | My mouth is dry. I'm thirsty. | Mulut saya kering, saya haus. |
| nausea | I feel sick to my stomach. | Saya mual. |
| itch | I'm itchy. | Saya gatal. |
| position | Please change my position. | Tolong ubah posisi saya. |
| hands_uncomfortable | My hands or arms are uncomfortable. | Tangan saya tidak nyaman. |
| toilet | I need the toilet, or I'm wet. | Saya perlu buang air, atau saya basah. |
| tired | I'm tired. I want to sleep. | Saya lelah, ingin tidur. |
| hot | I'm too hot. | Saya kepanasan. |
| cold | I'm cold. | Saya kedinginan. |
| light | The light is too bright. | Lampunya terlalu terang. |
| noise | It's too noisy. | Terlalu berisik. |
| what_happened | What happened to me? | Apa yang terjadi pada saya? |
| where | Where am I? | Saya di mana? |
| time | What day and time is it? | Hari dan jam berapa sekarang? |
| tube_when | When will the tube come out? | Kapan selangnya dilepas? |
| talk_staff | I want to talk with my doctor or nurse. | Saya ingin bicara dengan dokter atau perawat. |
| scared | I'm scared. | Saya takut. |
| company | Please stay with me. | Tolong temani saya. |
| thanks | Thank you. | Terima kasih. |
| see_person | I want to see my {relation}, {name}. | Saya ingin bertemu {relation_id} saya, {name}. |
| where_person | Where is my {relation}, {name}? | Di mana {relation_id} saya, {name}? |
| call_person | Please call my {relation}, {name}. | Tolong telepon {relation_id} saya, {name}. |
| want_item | I want my {item}. | Saya ingin {item_id} saya. |
| tell_family_ok | Tell my family I'm okay. | Sampaikan ke keluarga bahwa saya baik-baik saja. |
| pray | I want to pray or hear prayers. | Saya ingin berdoa atau mendengarkan doa. |
| glasses_hearing | I want my glasses or hearing aid. | Saya ingin kacamata atau alat bantu dengar saya. |
| phone_music | I want my phone or some music. | Saya ingin HP saya atau mendengar musik. |
| spell | I want to spell something. | Saya ingin mengeja sesuatu. |
| stop | Stop asking for now. | Berhenti dulu. |
| other | Something else. | Hal lain. |
| pain location | The pain is in my chest. | Sakitnya di dada saya. |
| worse | It is worse than before. | Rasanya lebih sakit dari sebelumnya. |

Relations: daughter putri, son putra, child anak, wife istri, husband suami, mother ibu, father ayah,
sister saudari, brother saudara, grandchild cucu, grandmother nenek, grandfather kakek, aunt bibi,
uncle paman, cousin sepupu, niece/nephew keponakan, in-law menantu, friend teman, neighbour tetangga.
Question: "saudari"/"saudara" are formal; would "kakak/adik" be better (needs older/younger)?

## Questions (spoken to the patient)

| English | Indonesian |
|---|---|
| Is it about your body? | Apakah ini tentang tubuh {hon}? |
| Is it about breathing or your throat? | Apakah ini tentang napas atau tenggorokan? |
| Is it about pain? | Apakah ini tentang rasa sakit? |
| Is it about your mouth or stomach? | Apakah ini tentang mulut atau perut? |
| Is it about your arms, hands, or skin? | Apakah ini tentang tangan atau kulit? |
| Is it about resting or moving in bed? | Apakah ini tentang istirahat atau posisi tidur? |
| Is it about the room, like light, noise, or temperature? | Apakah ini tentang ruangan, seperti lampu, suara, atau suhu? |
| Is it about feeling hot or cold? | Apakah ini tentang rasa panas atau dingin? |
| Is it about a person? | Apakah ini tentang seseorang? |
| Is it about your family? | Apakah ini tentang keluarga {hon}? |
| Is it a question you want answered? | Apakah {hon} ingin menanyakan sesuatu? |
| Is it about how you feel inside? | Apakah ini tentang perasaan {hon}? |
| Do you want something brought to you? | Apakah {hon} ingin dibawakan sesuatu? |
| Is it about the toilet? | Apakah ini tentang buang air? |
| Is it about the tube? | Apakah ini tentang selang? |
| Is it about prayer or faith? | Apakah ini tentang doa atau ibadah? |
| Is it about {name}? | Apakah ini tentang {name}? |
| Is this your message: "..."? | Apakah ini pesan {hon}: "..."? |
| Shall I say: "..."? | Boleh saya sampaikan: "..."? |
| Do you want to spell it? | Apakah {hon} ingin mengejanya? |
| Did I say it right? | Apakah yang saya sampaikan sudah benar? |
| Is your letter in this group? | Apakah huruf {hon} ada di kelompok ini? |
| Is everything so far correct? | Apakah sejauh ini sudah benar? |
| Is your word KUCING? | Apakah kata {hon} KUCING? |
| Do you mean: "..."? | Maksud {hon}: "..."? |
| Do you want to keep spelling? | Apakah {hon} ingin lanjut mengeja? |
| Can I ask where it hurts? | Boleh saya tanya di mana yang sakit? |
| Is it worse than before? | Apakah lebih sakit dari sebelumnya? |

Each taxonomy message also has a direct question (e.g. "Apakah {hon} merasa sakit?", "Apakah mulut
{hon} kering?", "Apakah lendirnya perlu disedot?"); see `direct_id` in the taxonomy file.

## Alarm and status

| English | Indonesian |
|---|---|
| The patient needs help now. | Pasien butuh bantuan sekarang. |
| Responses unclear. Please check with the patient in person. | Jawaban kurang jelas. Mohon periksa pasien secara langsung. |

## Open questions for the reviewer

1. Bapak/Ibu as "you" throughout, or mix with "Anda" for younger patients?
2. "Disedot" for suction: is "dibersihkan lendirnya" more natural for patients?
3. Banjar: worth adding a third language for South Kalimantan? It is not among the languages we found validated for Voice Transcribe.
