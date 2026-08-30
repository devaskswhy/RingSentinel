/**
 * The spoken explanations, in every language the card offers.
 *
 * Every number is checked against the repo — the four signal weights against
 * `detection/config.py`, the sweep against §5b, both thresholds against the
 * detector. A spoken claim is harder to fact-check than a written one because a
 * listener cannot scan back, so these are held to the page's standard and the
 * transcript is always shown beside the audio.
 *
 * On translation, honestly: these are real translations of the English scripts,
 * not a Hindi voice reading English words. Pointing `speechSynthesis` at
 * foreign text with a `lang` tag alone produces phonetic nonsense, which is
 * worse than offering English only. What is NOT translated is anything Claude
 * wrote — a cluster's case file exists in one language, and the card says so
 * rather than machine-translating an artefact the audit log records.
 *
 * `source` is not decoration. It is the line between "Claude wrote this about
 * this cluster" and "we wrote this and the browser is reading it aloud".
 */

export type LangCode = "en" | "hi" | "es" | "fr" | "de" | "pt" | "ja" | "ar";

export interface Language {
  code: LangCode;
  label: string;
  /** Matched as a prefix against `SpeechSynthesisVoice.lang`. */
  bcp47: string;
  dir: "ltr" | "rtl";
}

export const LANGUAGES: Language[] = [
  { code: "en", label: "English", bcp47: "en-US", dir: "ltr" },
  { code: "hi", label: "हिन्दी", bcp47: "hi-IN", dir: "ltr" },
  { code: "es", label: "Español", bcp47: "es-ES", dir: "ltr" },
  { code: "fr", label: "Français", bcp47: "fr-FR", dir: "ltr" },
  { code: "de", label: "Deutsch", bcp47: "de-DE", dir: "ltr" },
  { code: "pt", label: "Português", bcp47: "pt-BR", dir: "ltr" },
  { code: "ja", label: "日本語", bcp47: "ja-JP", dir: "ltr" },
  { code: "ar", label: "العربية", bcp47: "ar-SA", dir: "rtl" },
];

/** Playback rates. 0.5 for following along, 2 for someone who has heard it. */
export const RATES = [0.5, 1, 1.5, 1.75, 2] as const;

type Localised = Record<LangCode, string>;

export interface Explainer {
  id: string;
  question: Localised;
  text: Localised;
  /** Untranslated content (a Claude case file) says so here. */
  englishOnly?: boolean;
}

const WHY: Explainer = {
  id: "why",
  question: {
    en: "Why RingSentinel?",
    hi: "RingSentinel क्यों?",
    es: "¿Por qué RingSentinel?",
    fr: "Pourquoi RingSentinel ?",
    de: "Warum RingSentinel?",
    pt: "Por que RingSentinel?",
    ja: "なぜ RingSentinel なのか",
    ar: "لماذا RingSentinel؟",
  },
  text: {
    en: `Most fraud tools score one transaction at a time. That works for a stolen card, and it cannot work for a ring, because coordination does not exist inside a single transaction. It exists between them. RingSentinel builds a graph of which accounts share a device, an address, or a card, and scores the cluster instead of the transaction. On the seeded corpus that found 12 rings out of 12, with no false flags. Every score breaks into four named signals, so a reviewer can argue with the number rather than trust it. And nothing here can block, freeze, or decline anyone.`,
    hi: `ज़्यादातर फ़्रॉड टूल एक बार में एक ही पेमेंट को स्कोर करते हैं। चोरी हुए कार्ड के लिए यह काम करता है, लेकिन गिरोह के लिए नहीं, क्योंकि तालमेल किसी एक पेमेंट के अंदर नहीं होता। वह पेमेंट्स के बीच होता है। RingSentinel एक ग्राफ़ बनाता है कि कौन से अकाउंट एक ही डिवाइस, पता या कार्ड साझा करते हैं, और पेमेंट की जगह पूरे क्लस्टर को स्कोर करता है। हमारे डेटा पर इसने 12 में से 12 गिरोह पकड़े, बिना किसी ग़लत फ़्लैग के। हर स्कोर चार नामित संकेतों में बँटता है, ताकि समीक्षक उस पर भरोसा करने के बजाय बहस कर सके। और यहाँ कुछ भी किसी को ब्लॉक या फ़्रीज़ नहीं कर सकता।`,
    es: `La mayoría de las herramientas antifraude puntúan un pago cada vez. Eso sirve para una tarjeta robada, pero no para una red, porque la coordinación no existe dentro de un solo pago: existe entre ellos. RingSentinel construye un grafo de qué cuentas comparten dispositivo, dirección o tarjeta, y puntúa el grupo en lugar del pago. Sobre el corpus generado encontró 12 redes de 12, sin falsos positivos. Cada puntuación se descompone en cuatro señales con nombre, así que un revisor puede discutir el número en vez de confiar en él. Y nada aquí puede bloquear ni congelar a nadie.`,
    fr: `La plupart des outils antifraude évaluent un paiement à la fois. Cela fonctionne pour une carte volée, mais pas pour un réseau, car la coordination n'existe pas à l'intérieur d'un paiement : elle existe entre eux. RingSentinel construit un graphe des comptes qui partagent un appareil, une adresse ou une carte, et évalue le groupe plutôt que le paiement. Sur le corpus généré, il a trouvé 12 réseaux sur 12, sans faux positifs. Chaque score se décompose en quatre signaux nommés, si bien qu'un analyste peut discuter le chiffre au lieu de lui faire confiance. Et rien ici ne peut bloquer qui que ce soit.`,
    de: `Die meisten Betrugswerkzeuge bewerten eine Zahlung nach der anderen. Das reicht für eine gestohlene Karte, aber nicht für einen Ring, denn Koordination existiert nicht innerhalb einer einzelnen Zahlung. Sie existiert zwischen ihnen. RingSentinel baut einen Graphen darüber, welche Konten ein Gerät, eine Adresse oder eine Karte teilen, und bewertet die Gruppe statt der Zahlung. Auf dem erzeugten Datensatz fand das 12 von 12 Ringen, ohne Fehlalarme. Jeder Wert zerfällt in vier benannte Signale, sodass ein Prüfer die Zahl hinterfragen kann, statt ihr zu vertrauen. Und nichts hier kann jemanden sperren oder einfrieren.`,
    pt: `A maioria das ferramentas antifraude avalia um pagamento por vez. Isso funciona para um cartão roubado, mas não para uma quadrilha, porque a coordenação não existe dentro de um único pagamento: ela existe entre eles. O RingSentinel monta um grafo de quais contas compartilham dispositivo, endereço ou cartão, e avalia o grupo em vez do pagamento. No corpus gerado, encontrou 12 de 12 quadrilhas, sem falsos positivos. Cada pontuação se decompõe em quatro sinais nomeados, então um analista pode questionar o número em vez de confiar nele. E nada aqui pode bloquear ou congelar ninguém.`,
    ja: `多くの不正検知ツールは、支払いを一件ずつ評価します。盗難カードには有効ですが、組織的な不正には通用しません。共謀は一件の支払いの中には存在せず、支払いと支払いの「間」に存在するからです。RingSentinel は、どのアカウントが端末、住所、カードを共有しているかのグラフを作り、支払いではなくクラスタを評価します。生成したデータでは、12件中12件の組織を検出し、誤検知はゼロでした。スコアは4つの名前付きシグナルに分解されるため、担当者は数字を信じるのではなく、その根拠を検証できます。そしてここでは、誰かを遮断したり凍結したりすることはできません。`,
    ar: `معظم أدوات كشف الاحتيال تقيّم عملية دفع واحدة في كل مرة. هذا يصلح لبطاقة مسروقة، لكنه لا يصلح لشبكة منظّمة، لأن التنسيق لا يوجد داخل عملية دفع واحدة، بل بين العمليات. يبني RingSentinel رسمًا بيانيًا للحسابات التي تتشارك جهازًا أو عنوانًا أو بطاقة، ويقيّم المجموعة بدل العملية. على البيانات المولّدة، وجد 12 شبكة من أصل 12 دون أي إنذار خاطئ. وكل درجة تتحلّل إلى أربع إشارات مسمّاة، فيستطيع المراجع مناقشة الرقم بدل الوثوق به. ولا شيء هنا يستطيع حظر أحد أو تجميد حسابه.`,
  },
};

const FLAGGING: Explainer = {
  id: "flagging",
  question: {
    en: "How does flagging work?",
    hi: "फ़्लैगिंग कैसे काम करती है?",
    es: "¿Cómo funciona el marcado?",
    fr: "Comment fonctionne le signalement ?",
    de: "Wie funktioniert die Markierung?",
    pt: "Como funciona a marcação?",
    ja: "検出の仕組みは？",
    ar: "كيف يعمل وضع العلامات؟",
  },
  text: {
    en: `Four signals, each measured and weighted. Attribute reuse, at 45 percent, asks how many separate accounts funnel through one card, device, or address. Timing regularity, at 25 percent, asks whether the gaps between transactions look like a person or a script. Concentration asks how much of the cluster's volume runs through the shared attribute. Account shallowness asks whether these accounts have real histories, or exist only to place one discounted order. A shared address counts for less than a shared card, deliberately. Households share addresses. A weight of 0.4 is what keeps a family from being flagged as a crew.`,
    hi: `चार संकेत, हर एक मापा और भारित। एट्रिब्यूट रीयूज़, 45 प्रतिशत पर, पूछता है कि कितने अलग-अलग अकाउंट एक ही कार्ड, डिवाइस या पते से गुज़रते हैं। टाइमिंग रेगुलैरिटी, 25 प्रतिशत पर, पूछती है कि पेमेंट्स के बीच का अंतराल किसी इंसान जैसा है या स्क्रिप्ट जैसा। कंसंट्रेशन पूछता है कि क्लस्टर का कितना हिस्सा साझा एट्रिब्यूट से होकर जाता है। अकाउंट शैलोनेस पूछता है कि इन अकाउंट्स का असली इतिहास है या वे सिर्फ़ एक डिस्काउंट ऑर्डर के लिए बने हैं। साझा पता, साझा कार्ड से कम गिना जाता है — जानबूझकर। परिवार एक ही पता साझा करते हैं। 0.4 का भार ही एक परिवार को गिरोह समझे जाने से बचाता है।`,
    es: `Cuatro señales, cada una medida y ponderada. La reutilización de atributos, al 45 por ciento, pregunta cuántas cuentas distintas pasan por una misma tarjeta, dispositivo o dirección. La regularidad temporal, al 25 por ciento, pregunta si los intervalos entre pagos parecen humanos o de un script. La concentración mide qué parte del volumen del grupo pasa por el atributo compartido. La superficialidad de cuenta pregunta si esas cuentas tienen historial real o existen solo para un pedido con descuento. Una dirección compartida pesa menos que una tarjeta compartida, deliberadamente. Las familias comparten dirección. Un peso de 0,4 es lo que impide marcar a una familia como una red.`,
    fr: `Quatre signaux, chacun mesuré et pondéré. La réutilisation d'attributs, à 45 pour cent, demande combien de comptes distincts passent par une même carte, un même appareil ou une même adresse. La régularité temporelle, à 25 pour cent, demande si les intervalles entre paiements ressemblent à un humain ou à un script. La concentration mesure quelle part du volume du groupe passe par l'attribut partagé. La superficialité des comptes demande s'ils ont un vrai historique ou n'existent que pour une commande remisée. Une adresse partagée compte moins qu'une carte partagée, délibérément. Les familles partagent une adresse. Un poids de 0,4 empêche de signaler une famille comme un réseau.`,
    de: `Vier Signale, jedes gemessen und gewichtet. Attribut-Wiederverwendung, mit 45 Prozent, fragt, wie viele getrennte Konten durch dieselbe Karte, dasselbe Gerät oder dieselbe Adresse laufen. Zeitliche Regelmäßigkeit, mit 25 Prozent, fragt, ob die Abstände zwischen Zahlungen nach einem Menschen oder nach einem Skript aussehen. Konzentration misst, wie viel Volumen der Gruppe durch das geteilte Attribut fließt. Kontotiefe fragt, ob diese Konten echte Historien haben oder nur für eine rabattierte Bestellung existieren. Eine geteilte Adresse zählt bewusst weniger als eine geteilte Karte. Haushalte teilen Adressen. Ein Gewicht von 0,4 verhindert, dass eine Familie als Bande markiert wird.`,
    pt: `Quatro sinais, cada um medido e ponderado. A reutilização de atributos, com 45 por cento, pergunta quantas contas distintas passam por um mesmo cartão, dispositivo ou endereço. A regularidade temporal, com 25 por cento, pergunta se os intervalos entre pagamentos parecem humanos ou de um script. A concentração mede quanto do volume do grupo passa pelo atributo compartilhado. A superficialidade das contas pergunta se elas têm histórico real ou existem só para um pedido com desconto. Um endereço compartilhado pesa menos que um cartão compartilhado, de propósito. Famílias compartilham endereço. Um peso de 0,4 é o que impede marcar uma família como quadrilha.`,
    ja: `シグナルは4つ、それぞれ測定され重み付けされています。属性の再利用は45パーセントの重みで、いくつの別々のアカウントが同じカード・端末・住所を通っているかを見ます。タイミングの規則性は25パーセントで、支払いの間隔が人間らしいかスクリプトらしいかを見ます。集中度は、クラスタの取引量のうちどれだけが共有属性を通るかを見ます。アカウントの浅さは、実際の履歴があるのか、割引注文一件のためだけに存在するのかを見ます。共有住所は共有カードより軽く扱われます。これは意図的です。家族は住所を共有するからです。重み0.4が、家族を犯行グループとして扱わないための歯止めです。`,
    ar: `أربع إشارات، كل واحدة مقاسة وموزونة. إعادة استخدام السمات، بوزن 45 بالمئة، تسأل كم حسابًا منفصلًا يمر عبر البطاقة أو الجهاز أو العنوان نفسه. انتظام التوقيت، بوزن 25 بالمئة، يسأل إن كانت الفواصل بين المدفوعات تبدو بشرية أم آلية. التركيز يقيس كم من حجم المجموعة يمر عبر السمة المشتركة. وسطحية الحساب تسأل إن كان لهذه الحسابات تاريخ حقيقي أم أنها وُجدت لطلب مخفّض واحد فقط. العنوان المشترك يُحتسب أقل من البطاقة المشتركة، وهذا مقصود، لأن الأسر تتشارك العناوين. وزن 0.4 هو ما يمنع اعتبار عائلة شبكة احتيال.`,
  },
};

const CALIBRATION: Explainer = {
  id: "calibration",
  question: {
    en: "How was the threshold chosen?",
    hi: "थ्रेशोल्ड कैसे तय हुई?",
    es: "¿Cómo se eligió el umbral?",
    fr: "Comment le seuil a-t-il été choisi ?",
    de: "Wie wurde der Schwellenwert gewählt?",
    pt: "Como o limiar foi escolhido?",
    ja: "しきい値はどう決めたのか",
    ar: "كيف اختير الحد الفاصل؟",
  },
  text: {
    en: `The threshold is 0.3, and it was measured rather than chosen. Sweeping it across the tuning split, anything between 0.25 and 0.35 found all 8 rings with zero false flags. Below that band a false flag appears. Above 0.4, real rings start being missed. 0.3 sits in the centre of the flat region, and that is the whole point. The weakest cluster scores 0.37, so the threshold could move seven hundredths and nothing at all would change. A threshold in the middle of a plateau is a measurement. One perched on a cliff edge is a fit.`,
    hi: `थ्रेशोल्ड 0.3 है, और यह चुनी नहीं गई — मापी गई है। ट्यूनिंग सेट पर इसे घुमाने पर, 0.25 से 0.35 के बीच कोई भी मान आठों गिरोह पकड़ता है, बिना किसी ग़लत फ़्लैग के। इससे नीचे एक ग़लत फ़्लैग आ जाता है। 0.4 से ऊपर असली गिरोह छूटने लगते हैं। 0.3 उस समतल हिस्से के बीच में बैठती है, और यही पूरी बात है। सबसे कमज़ोर क्लस्टर का स्कोर 0.37 है, यानी थ्रेशोल्ड सात सौवें हिस्से तक हिल सकती है और कुछ नहीं बदलेगा। पठार के बीच की थ्रेशोल्ड एक माप है। चट्टान के किनारे बैठी थ्रेशोल्ड सिर्फ़ फ़िटिंग है।`,
    es: `El umbral es 0,3, y fue medido, no elegido. Al recorrerlo sobre el conjunto de ajuste, cualquier valor entre 0,25 y 0,35 encontró las 8 redes sin falsos positivos. Por debajo aparece un falso positivo. Por encima de 0,4 empiezan a perderse redes reales. 0,3 está en el centro de la región plana, y ese es todo el argumento. El grupo más débil puntúa 0,37, así que el umbral podría moverse siete centésimas sin que cambiara nada. Un umbral en mitad de una meseta es una medición. Uno al borde de un acantilado es un ajuste a medida.`,
    fr: `Le seuil est 0,3, et il a été mesuré, non choisi. En le balayant sur le jeu de calibrage, toute valeur entre 0,25 et 0,35 trouvait les 8 réseaux sans aucun faux positif. En dessous, un faux positif apparaît. Au-dessus de 0,4, de vrais réseaux commencent à être manqués. 0,3 se trouve au centre de la région plate, et c'est tout l'argument. Le groupe le plus faible obtient 0,37 : le seuil pourrait bouger de sept centièmes sans que rien ne change. Un seuil au milieu d'un plateau est une mesure. Un seuil au bord d'une falaise est un ajustement.`,
    de: `Der Schwellenwert ist 0,3, und er wurde gemessen, nicht gewählt. Beim Durchlauf über den Kalibrierungssatz fand jeder Wert zwischen 0,25 und 0,35 alle 8 Ringe ohne Fehlalarme. Darunter erscheint ein Fehlalarm. Über 0,4 werden echte Ringe übersehen. 0,3 liegt in der Mitte des flachen Bereichs, und genau darum geht es. Der schwächste Cluster erreicht 0,37, der Schwellenwert könnte sich also um sieben Hundertstel bewegen, ohne dass sich irgendetwas ändert. Ein Schwellenwert mitten auf einem Plateau ist eine Messung. Einer am Rand einer Klippe ist eine Anpassung.`,
    pt: `O limiar é 0,3, e ele foi medido, não escolhido. Percorrendo-o sobre o conjunto de ajuste, qualquer valor entre 0,25 e 0,35 encontrou as 8 quadrilhas sem falsos positivos. Abaixo disso aparece um falso positivo. Acima de 0,4, quadrilhas reais começam a passar despercebidas. 0,3 fica no centro da região plana, e esse é todo o argumento. O grupo mais fraco pontua 0,37, então o limiar poderia se mover sete centésimos sem que nada mudasse. Um limiar no meio de um platô é uma medição. Um na beira de um precipício é um ajuste.`,
    ja: `しきい値は0.3で、選んだのではなく測って決めました。調整用データで動かしてみると、0.25から0.35のあいだであれば、8件すべての組織を誤検知ゼロで検出できました。それより下では誤検知が1件現れます。0.4を超えると、本物の組織を取りこぼし始めます。0.3はその平坦な領域の中央にあり、それこそが要点です。最も弱いクラスタのスコアは0.37なので、しきい値が0.07動いても何も変わりません。台地の真ん中にあるしきい値は測定です。崖のふちにあるしきい値は、ただの当てはめです。`,
    ar: `الحد الفاصل هو 0.3، وقد قيس ولم يُختر. عند تحريكه عبر مجموعة المعايرة، وجدت أي قيمة بين 0.25 و0.35 الشبكات الثماني كلها دون أي إنذار خاطئ. وتحت ذلك يظهر إنذار خاطئ. وفوق 0.4 تبدأ شبكات حقيقية بالإفلات. يقع 0.3 في منتصف المنطقة المستوية، وهذا هو بيت القصيد. أضعف مجموعة تسجّل 0.37، أي أن الحد يمكن أن يتحرك سبعة أجزاء من مئة دون أن يتغير شيء. الحد الواقع في منتصف هضبة هو قياس. أما الواقع على حافة منحدر فهو مجرد تفصيل على المقاس.`,
  },
};

const PAGE: Explainer = {
  id: "page",
  question: {
    en: "What is this page?",
    hi: "यह पेज क्या है?",
    es: "¿Qué es esta página?",
    fr: "Qu'est-ce que cette page ?",
    de: "Was ist diese Seite?",
    pt: "O que é esta página?",
    ja: "この画面は何か",
    ar: "ما هذه الصفحة؟",
  },
  text: {
    en: `This is the review queue. Every row is a cluster of accounts the detector flagged as possibly coordinated. Never a single transaction, always a group. Nothing on this page has been acted on. A flag is a request for your attention, not a decision, and no code path in this system can block, freeze, or decline anyone. Select any cluster and its full case opens below: what Claude wrote about it, the four signals behind the score, the accounts and what they share, and the decision, which is yours to make.`,
    hi: `यह समीक्षा कतार है। हर पंक्ति उन अकाउंट्स का एक क्लस्टर है जिन्हें डिटेक्टर ने संभावित रूप से आपस में जुड़ा हुआ पाया। कभी एक अकेला पेमेंट नहीं, हमेशा एक समूह। इस पेज पर किसी चीज़ पर कार्रवाई नहीं हुई है। फ़्लैग एक फ़ैसला नहीं, आपके ध्यान का अनुरोध है, और इस सिस्टम का कोई भी हिस्सा किसी को ब्लॉक या फ़्रीज़ नहीं कर सकता। किसी भी क्लस्टर को चुनें और उसका पूरा केस नीचे खुलेगा: Claude ने उसके बारे में क्या लिखा, स्कोर के पीछे के चार संकेत, अकाउंट और वे क्या साझा करते हैं, और फ़ैसला — जो आपका है।`,
    es: `Esta es la cola de revisión. Cada fila es un grupo de cuentas que el detector marcó como posiblemente coordinadas. Nunca un pago aislado, siempre un grupo. Nada en esta página ha sido ejecutado. Una marca es una petición de atención, no una decisión, y ninguna parte de este sistema puede bloquear ni congelar a nadie. Selecciona un grupo y su caso completo se abre debajo: lo que Claude escribió, las cuatro señales tras la puntuación, las cuentas y lo que comparten, y la decisión, que es tuya.`,
    fr: `Voici la file de revue. Chaque ligne est un groupe de comptes que le détecteur a signalé comme possiblement coordonnés. Jamais un paiement isolé, toujours un groupe. Rien sur cette page n'a été exécuté. Un signalement est une demande d'attention, pas une décision, et aucune partie de ce système ne peut bloquer qui que ce soit. Sélectionnez un groupe et son dossier complet s'ouvre en dessous : ce que Claude en a écrit, les quatre signaux derrière le score, les comptes et ce qu'ils partagent, et la décision, qui vous revient.`,
    de: `Dies ist die Prüfliste. Jede Zeile ist eine Gruppe von Konten, die der Detektor als möglicherweise koordiniert markiert hat. Nie eine einzelne Zahlung, immer eine Gruppe. Auf dieser Seite wurde nichts ausgeführt. Eine Markierung ist eine Bitte um Aufmerksamkeit, keine Entscheidung, und kein Teil dieses Systems kann jemanden sperren oder einfrieren. Wählen Sie eine Gruppe, und der vollständige Fall öffnet sich darunter: was Claude dazu geschrieben hat, die vier Signale hinter der Bewertung, die Konten und was sie teilen, und die Entscheidung, die Ihnen gehört.`,
    pt: `Esta é a fila de revisão. Cada linha é um grupo de contas que o detector marcou como possivelmente coordenadas. Nunca um pagamento isolado, sempre um grupo. Nada nesta página foi executado. Uma marcação é um pedido de atenção, não uma decisão, e nenhuma parte deste sistema pode bloquear ou congelar ninguém. Selecione um grupo e o caso completo abre abaixo: o que Claude escreveu, os quatro sinais por trás da pontuação, as contas e o que compartilham, e a decisão, que é sua.`,
    ja: `これはレビュー待ちの一覧です。各行は、検出器が連携の疑いありと判断したアカウントのまとまりです。単独の支払いではなく、常にグループです。この画面では何も実行されていません。フラグは判断ではなく、注意を向けてほしいという合図であり、このシステムのどこにも誰かを遮断・凍結する経路はありません。クラスタを選ぶと、その全体が下に開きます。Claude が書いた説明、スコアの根拠となる4つのシグナル、アカウントと共有している情報、そして判断です。判断はあなたのものです。`,
    ar: `هذه قائمة المراجعة. كل صف مجموعة حسابات رصدها النظام كمحتمل أن تكون منسّقة. ليست عملية دفع واحدة أبدًا، بل مجموعة دائمًا. لم يُنفَّذ أي إجراء في هذه الصفحة. العلامة طلب لانتباهك وليست قرارًا، ولا يوجد في هذا النظام أي مسار يستطيع حظر أحد أو تجميد حسابه. اختر أي مجموعة لتُفتح حالتها كاملة في الأسفل: ما كتبه Claude عنها، والإشارات الأربع خلف الدرجة، والحسابات وما تتشاركه، ثم القرار، وهو قرارك أنت.`,
  },
};

const WORKFLOW: Explainer = {
  id: "workflow",
  question: {
    en: "What should I do here?",
    hi: "मुझे यहाँ क्या करना है?",
    es: "¿Qué debo hacer aquí?",
    fr: "Que dois-je faire ici ?",
    de: "Was soll ich hier tun?",
    pt: "O que devo fazer aqui?",
    ja: "ここで何をすればよいか",
    ar: "ماذا أفعل هنا؟",
  },
  text: {
    en: `Seven steps, numbered down the panel. Read Claude's case file first. It is plain language, and it is advisory only. Then check the four signals, because the score is a sum of named parts rather than a model output. Step three tells you how close it was: the smallest change that would have flipped the verdict. Step four is the graph of accounts and what they share. Step five is your decision, and it needs a written reason. The database refuses a decision without one. Step six is the audit trail, which cannot be rewritten. Step seven rebuilds the evidence pack and re-verifies the hash chain, live.`,
    hi: `सात चरण, पैनल में क्रमांकित। पहले Claude की केस फ़ाइल पढ़ें। वह सरल भाषा में है और सिर्फ़ सलाह है। फिर चार संकेत जाँचें, क्योंकि स्कोर किसी मॉडल का आउटपुट नहीं, नामित हिस्सों का जोड़ है। तीसरा चरण बताता है कि फ़ैसला कितना क़रीब था — वह सबसे छोटा बदलाव जो नतीजा पलट देता। चौथा चरण अकाउंट्स का ग्राफ़ है। पाँचवाँ आपका फ़ैसला है, और उसके लिए लिखित कारण ज़रूरी है; डेटाबेस बिना कारण फ़ैसला स्वीकार नहीं करता। छठा ऑडिट ट्रेल है, जिसे दोबारा लिखा नहीं जा सकता। सातवाँ चरण एविडेंस पैक दोबारा बनाकर हैश चेन को वहीं जाँचता है।`,
    es: `Siete pasos, numerados en el panel. Lee primero el informe de Claude: lenguaje llano, y solo consultivo. Luego revisa las cuatro señales, porque la puntuación es una suma de partes con nombre, no la salida de un modelo. El paso tres te dice cuán cerca estuvo: el cambio más pequeño que habría invertido el veredicto. El paso cuatro es el grafo de cuentas y lo que comparten. El paso cinco es tu decisión, y necesita un motivo escrito; la base de datos rechaza una decisión sin él. El paso seis es el registro de auditoría, que no puede reescribirse. El paso siete reconstruye el paquete de evidencia y vuelve a verificar la cadena de hashes, en vivo.`,
    fr: `Sept étapes, numérotées dans le panneau. Lisez d'abord le dossier de Claude : langage clair, et purement consultatif. Vérifiez ensuite les quatre signaux, car le score est une somme de composantes nommées, pas la sortie d'un modèle. L'étape trois vous dit à quel point c'était serré : le plus petit changement qui aurait inversé le verdict. L'étape quatre est le graphe des comptes et de ce qu'ils partagent. L'étape cinq est votre décision, et elle exige un motif écrit ; la base de données refuse une décision sans motif. L'étape six est le journal d'audit, qui ne peut être réécrit. L'étape sept reconstruit le dossier de preuve et revérifie la chaîne de hachage, en direct.`,
    de: `Sieben Schritte, im Panel nummeriert. Lesen Sie zuerst Claudes Fallakte: einfache Sprache, und rein beratend. Prüfen Sie dann die vier Signale, denn der Wert ist eine Summe benannter Teile, nicht die Ausgabe eines Modells. Schritt drei sagt Ihnen, wie knapp es war: die kleinste Änderung, die das Urteil gekippt hätte. Schritt vier ist der Graph der Konten und was sie teilen. Schritt fünf ist Ihre Entscheidung, und sie braucht eine schriftliche Begründung; die Datenbank verweigert eine Entscheidung ohne sie. Schritt sechs ist das Prüfprotokoll, das nicht umgeschrieben werden kann. Schritt sieben baut das Beweispaket neu auf und prüft die Hash-Kette erneut, live.`,
    pt: `Sete passos, numerados no painel. Leia primeiro o relatório do Claude: linguagem simples, e apenas consultivo. Depois confira os quatro sinais, porque a pontuação é uma soma de partes nomeadas, não a saída de um modelo. O passo três diz o quão perto foi: a menor mudança que teria invertido o veredito. O passo quatro é o grafo das contas e do que compartilham. O passo cinco é a sua decisão, e ela exige um motivo escrito; o banco de dados recusa uma decisão sem ele. O passo seis é a trilha de auditoria, que não pode ser reescrita. O passo sete reconstrói o pacote de evidências e reverifica a cadeia de hashes, ao vivo.`,
    ja: `手順は7つ、パネルに番号が振ってあります。まず Claude のケースファイルを読んでください。平易な言葉で書かれた、あくまで助言です。次に4つのシグナルを確認します。スコアはモデルの出力ではなく、名前のついた要素の合計だからです。3番目は「どれだけ際どかったか」、つまり判定を覆すのに必要な最小の変化を示します。4番目はアカウントと共有情報のグラフ。5番目はあなたの判断で、記述された理由が必要です。理由のない判断はデータベースが拒否します。6番目は書き換え不可能な監査記録。7番目は証拠パックを再構築し、ハッシュチェーンをその場で再検証します。`,
    ar: `سبع خطوات، مرقّمة في اللوحة. اقرأ ملف Claude أولًا: لغة واضحة، وهو استشاري فقط. ثم افحص الإشارات الأربع، لأن الدرجة مجموع أجزاء مسمّاة وليست ناتج نموذج. الخطوة الثالثة تخبرك كم كان الأمر قريبًا: أصغر تغيير كان سيقلب النتيجة. الرابعة هي رسم الحسابات وما تتشاركه. الخامسة قرارك، ويحتاج سببًا مكتوبًا؛ وقاعدة البيانات ترفض أي قرار بلا سبب. السادسة سجل التدقيق، ولا يمكن إعادة كتابته. والسابعة تعيد بناء حزمة الأدلة وتتحقق من سلسلة التجزئة مباشرة.`,
  },
};

const STATES: Explainer = {
  id: "states",
  question: {
    en: "Pending, ambiguous — what's the difference?",
    hi: "पेंडिंग और अस्पष्ट में क्या फ़र्क़ है?",
    es: "Pendiente o ambiguo, ¿cuál es la diferencia?",
    fr: "En attente ou ambigu, quelle différence ?",
    de: "Ausstehend oder mehrdeutig — der Unterschied?",
    pt: "Pendente ou ambíguo, qual a diferença?",
    ja: "保留と判断保留の違い",
    ar: "معلّق أم غامض، ما الفرق؟",
  },
  text: {
    en: `Three states, and the difference matters. Pending means flagged, and the detector is confident. Ambiguous means flagged, but the score landed between 0.3 and 0.45. The detector is telling you it is unsure, rather than forcing a binary it cannot support. Both still mean a human has to look. Approved and dismissed are decisions, and only a human review action can set them. Once recorded, a decision is never revised. The trigger refuses it even inside a review, because otherwise the audit log would disagree with the row it describes.`,
    hi: `तीन स्थितियाँ, और फ़र्क़ मायने रखता है। पेंडिंग का मतलब है फ़्लैग किया गया और डिटेक्टर आश्वस्त है। अस्पष्ट का मतलब है फ़्लैग तो हुआ, पर स्कोर 0.3 और 0.45 के बीच गिरा। डिटेक्टर आपको बता रहा है कि वह अनिश्चित है, बजाय एक ऐसा दो-टूक नतीजा थोपने के जिसे वह साबित नहीं कर सकता। दोनों का मतलब है कि इंसान को देखना ही होगा। स्वीकृत और ख़ारिज — ये फ़ैसले हैं, और इन्हें सिर्फ़ मानवीय समीक्षा ही तय कर सकती है। एक बार दर्ज होने के बाद फ़ैसला कभी नहीं बदलता; ट्रिगर समीक्षा के भीतर भी इनकार कर देता है, वरना ऑडिट लॉग उसी पंक्ति से असहमत हो जाएगा जिसका वह वर्णन करता है।`,
    es: `Tres estados, y la diferencia importa. Pendiente significa marcado, con el detector seguro. Ambiguo significa marcado, pero con una puntuación entre 0,3 y 0,45: el detector te está diciendo que no está seguro, en vez de forzar un binario que no puede sostener. Ambos siguen exigiendo que mire una persona. Aprobado y descartado son decisiones, y solo una revisión humana puede fijarlas. Una vez registrada, una decisión nunca se revisa. El disparador la rechaza incluso dentro de una revisión, porque de lo contrario el registro de auditoría contradiría la fila que describe.`,
    fr: `Trois états, et la différence compte. En attente signifie signalé, avec un détecteur confiant. Ambigu signifie signalé, mais avec un score entre 0,3 et 0,45 : le détecteur vous dit qu'il n'est pas sûr, au lieu d'imposer un verdict binaire qu'il ne peut soutenir. Les deux exigent encore un regard humain. Approuvé et rejeté sont des décisions, et seule une revue humaine peut les fixer. Une fois enregistrée, une décision n'est jamais révisée. Le déclencheur la refuse même au sein d'une revue, sinon le journal d'audit contredirait la ligne qu'il décrit.`,
    de: `Drei Zustände, und der Unterschied zählt. Ausstehend heißt markiert, und der Detektor ist sicher. Mehrdeutig heißt markiert, aber die Bewertung lag zwischen 0,3 und 0,45: Der Detektor sagt Ihnen, dass er unsicher ist, statt ein Entweder-oder zu erzwingen, das er nicht belegen kann. Beide erfordern weiterhin einen menschlichen Blick. Bestätigt und verworfen sind Entscheidungen, und nur eine menschliche Prüfung kann sie setzen. Einmal erfasst, wird eine Entscheidung nie revidiert. Der Trigger verweigert das selbst innerhalb einer Prüfung, sonst widerspräche das Protokoll der Zeile, die es beschreibt.`,
    pt: `Três estados, e a diferença importa. Pendente significa marcado, com o detector confiante. Ambíguo significa marcado, mas com pontuação entre 0,3 e 0,45: o detector está dizendo que não tem certeza, em vez de forçar um binário que não sustenta. Os dois ainda exigem que uma pessoa olhe. Aprovado e descartado são decisões, e só uma revisão humana pode defini-las. Uma vez registrada, uma decisão nunca é revisada. O gatilho a recusa mesmo dentro de uma revisão, porque senão a trilha de auditoria contradiria a linha que descreve.`,
    ja: `状態は3つあり、その違いが重要です。「保留」は検出済みで、検出器が確信している状態。「判断保留」も検出済みですが、スコアが0.3から0.45のあいだに入った状態です。裏づけのない二択を押しつけるのではなく、確信が持てないと申告しています。どちらも人が見る必要があります。「承認」と「却下」は判断であり、人によるレビューだけが設定できます。いったん記録された判断は決して修正されません。レビューの中でもトリガーが拒否します。さもなければ監査記録が、それが説明している行と食い違ってしまうからです。`,
    ar: `ثلاث حالات، والفرق بينها مهم. «معلّق» يعني أنه رُصد والنظام واثق. و«غامض» يعني أنه رُصد لكن الدرجة وقعت بين 0.3 و0.45: النظام يخبرك أنه غير متأكد، بدل فرض حكم قاطع لا يستطيع إسناده. وكلاهما يتطلب أن ينظر إنسان. أما «معتمد» و«مرفوض» فهما قراران، ولا يضبطهما إلا مراجعة بشرية. وبمجرد تسجيل القرار لا يُراجَع أبدًا؛ يرفض المشغّل ذلك حتى داخل مراجعة، وإلا لتناقض سجل التدقيق مع الصف الذي يصفه.`,
  },
};

export const LANDING_EXPLAINERS: Explainer[] = [WHY, FLAGGING, CALIBRATION];
export const CONSOLE_EXPLAINERS: Explainer[] = [PAGE, WORKFLOW, STATES];

/** Fills every language slot with the same English string. */
function english(s: string): Localised {
  return { en: s, hi: s, es: s, fr: s, de: s, pt: s, ja: s, ar: s };
}

const CLUSTER_LABEL: Record<string, Localised> = {
  summary: {
    en: "Summarise this cluster",
    hi: "इस क्लस्टर का सारांश",
    es: "Resume este grupo",
    fr: "Résumer ce groupe",
    de: "Diese Gruppe zusammenfassen",
    pt: "Resumir este grupo",
    ja: "このクラスタの要約",
    ar: "لخّص هذه المجموعة",
  },
  graph: {
    en: "What does the graph show?",
    hi: "ग्राफ़ क्या दिखाता है?",
    es: "¿Qué muestra el grafo?",
    fr: "Que montre le graphe ?",
    de: "Was zeigt der Graph?",
    pt: "O que o grafo mostra?",
    ja: "グラフが示すもの",
    ar: "ماذا يُظهر الرسم البياني؟",
  },
  close: {
    en: "How close was this call?",
    hi: "यह फ़ैसला कितना क़रीब था?",
    es: "¿Qué tan ajustada fue la decisión?",
    fr: "À quel point était-ce serré ?",
    de: "Wie knapp war das?",
    pt: "Quão apertada foi a decisão?",
    ja: "判定はどれだけ際どかったか",
    ar: "كم كان القرار قريبًا؟",
  },
};

/**
 * Topics for the cluster currently open, built from its real data.
 *
 * The summary speaks CLAUDE'S OWN case file — its summary, confidence note and
 * key signals, in order. Not a paraphrase and not a second model pass: it is
 * the same artefact the audit log records, heard instead of read. That is also
 * why it is marked english-only rather than machine-translated; translating an
 * artefact would make the spoken version differ from the recorded one.
 *
 * The graph and counterfactual answers are assembled from the stored evidence,
 * so they too state only what the detector actually found.
 */
export function clusterExplainers(detail: {
  cluster: { score: number; cadence: string; status: string };
  case_file: {
    summary: string;
    confidence_note: string;
    key_signals: string[];
  } | null;
  evidence: {
    size: number;
    shared_attributes?: {
      attribute_type: string;
      customer_count: number;
      observations: number;
    }[];
  };
  graph: { nodes: unknown[]; edges: unknown[] };
  counterfactual: { reading: string; note: string } | null;
}): Explainer[] {
  const out: Explainer[] = [];

  if (detail.case_file) {
    const script = [
      detail.case_file.summary,
      detail.case_file.confidence_note,
      ...(detail.case_file.key_signals ?? []),
    ]
      .filter(Boolean)
      .join(" ");
    out.push({
      id: "cluster-summary",
      question: CLUSTER_LABEL.summary,
      text: english(script),
      englishOnly: true,
    });
  }

  const shared = detail.evidence.shared_attributes ?? [];
  if (shared.length) {
    const parts = shared
      .slice(0, 4)
      .map(
        (a) =>
          `${a.customer_count} accounts share one ${a.attribute_type}, seen across ${a.observations} transactions`,
      );
    out.push({
      id: "cluster-graph",
      question: CLUSTER_LABEL.graph,
      text: english(
        `This cluster holds ${detail.evidence.size} accounts, drawn as ${detail.graph.nodes.length} nodes and ${detail.graph.edges.length} connections. ${parts.join(". ")}. Circles are accounts and diamonds are the attributes they have in common. The convergence is the signal: any one account sharing a card is unremarkable, and ${detail.evidence.size} of them converging on the same one is not.`,
      ),
      englishOnly: true,
    });
  }

  if (detail.counterfactual) {
    out.push({
      id: "cluster-close",
      question: CLUSTER_LABEL.close,
      text: english(`${detail.counterfactual.reading} ${detail.counterfactual.note}`),
      englishOnly: true,
    });
  }

  return out;
}
