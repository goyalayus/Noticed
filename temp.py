from google import genai

client = genai.Client(api_key="AIzaSyAiwTesLibelvYhDT4UKsfKCplO06Ct-6Y")

INSTRUCTION_TEMPLATE = """You are an AI assistant generating Twitter replies based on a user's past style.
Generate a reply to the target tweet, adhering strictly to the provided speaking style.

Constraints:
- Max length: {max_chars} characters.
- Match the tone and vocabulary of the speaking style reference.
- Be humble and conversational if the style dictates.
- **CRITICAL: Output *ONLY* the raw tweet reply text.** No introductions, explanations, quotes, or extra formatting.

Speaking Style Reference Text:
--- START STYLE ---
"today’s os lecture reminded me of that scene from pantheon",
  "“today i walked” is one of the best things to happen to twitter",
  "RT @DavidZagaynov: Over the last 6 months we’ve been developing our first operational vehicle - The Poseidon Seagull",
  "your early 20s are for side-quests maxxing",
  "What's happening?",
  "it’s insane that we had paintings, music, gods and stuff before we had agriculture",
  "",
  "oh to be an art curator at the british museum, the louvre or the met",
  "going through a tech bro canon event\n\nlearning blender",
  "tyler cowen appeared in my dream today",
  "2025 is going to be epic",
  "why isn’t apple buying an island off the coast of sf and building a colossal statue of steve jobs holding an iphone?",
  "if you are young : try things → quickly figure out if the vibe matches → pivot fast if it doesn't",
  "RT @Samyak1729: hear me out",
  "",
  "something about the old wadas of pune",
  "japanese studios other than ghibli \n\nmadhouse\ntoei animation \nstudio pierrot\nproduction ig\nbones studio \nshaft",
  "i can’t stress this enough",
  "this gc sounds more interesting than potus’ warchat",
  "RT @dwarkesh_sp: Recorded an AMA!\n\nHad great fun shooting the shit with my friends @TrentonBricken &amp; @_sholtodouglas \n\nOn the new book, car…",
  "tfw your favourite youtuber drops a video after like three months",
  "me and auren\nme and chatgpt\nme and claude",
  "one of the saddest thing is seeing my friends who are really passionate about something but have to go the trad path because “parents”",
  "",
  "need a drama series focusing on the british history from the norman conquest till the coronation of elizabeth ii",
  "mclaren are going to win constructors again huh",
  "so fkin insane that nathan rothschild knew of napoleon’s defeat at waterloo before the british government and leveraged this information in the bond markets",
  "what google was supposed to be",
  "siri is dumb. google assistant is dumb. alexa is normie. we need something cool ahh shit, straight outta 2001 a space odyssey",
  "shipping the project today. github link below",
  "tried hot coffee + mogu mogu lychee accidentally and it was not bad surprisingly",
  "timothée is the greatest actor of our generation",
  "of what use is the art if you can’t show it to the one who inspired it",
  "a movie on the rivalry of ysl and karl lagerfeld directed by david fincher would go hard",
  "what would you collect if you had unlimited time and money?",
  "my college wifi has letterboxd on blocklist lol",
  "ysl became creative director of christian dior at 21",
  "universal basic grand tour",
  "we had no major movements since the backpacking/hippie culture of 60-70s which encouraged travel for experiences rather than luxury",
  "when was the last time your heart skipped a beat anon?",
  "i really thought oppenheimer was going to do for manufacturing what the social network did for software startups but alas we need to wait for the elon biopic now",
  "i fkin love my ipod",
  "bring back plato-aristotlian aristocracy",
  "having 100s of active tabs in your browser is really counterproductive",
  "overdosed on panipuri",
  "wrote few words about my experience",
  "made more spontaneous decisions in last three months than entire last year",
  "girl so good i started writing urdu poetry",
  "learned more about filmmaking on three days of shoot than watching 100s of video essays on yt",
  "RT @nearcyan: if you have even the slightest suspicion that you may be above-average  at anything, for the love of god, please do something…",
  "good morning",
  "oil money ruined middle east",
  "rather lie is the best track in carti’s music",
  "it’s really hard to choose between the ottoman and the abbasid empire",
  "",
  "almost said no to an opportunity…\n\nnow i am part of a feature film as a jr artist (extras lol) \n\nnever say no to side quests",
  "anyone good at game dev in pune. dm me",
  "",
  "doodling on school/college desks is a very underrated art genre",
  "jaggery + ghee tastes like childhood",
  "“i am nothing if not a democracy of ghosts”\n\nthis is art",
  "me vibe coding: haha fk yeah!!! yes!!   \n\nme vibe debugging: well this fucking sucks. wtf!",
  "another sunday, another post",
  "worst thing about claude",
  "where can i volunteer for archeological work in india?",
  "something like wework but for libraries ??",
  "had a long debate/conversation with my dad on relationships and responsibilities. it approached philosophical territory. i love his way of articulating stuff and using the best analogies. i have a lot to learn",
  "penguin has the best cover design game in the whole publication industry",
  "learning driving. let the adrenaline rushhh",
  "i need a cat and then i want to name it seagull",
  "almost got hit by a bus yesterday. it was fun",
  "been chatting with auren since last month and it’s really great. highly recommend trying it out if you want to chat with the highest EQ ai",
  "llm chat apps are almost like having personal aristocratic tutor but it’s not quite their yet. current apps lack the vibes (or maybe form factor). it’s not an engineering problem that’s for sure",
  "i miss @archillect everyday",
  "reminder that you can’t force ambition into someone",
  "the beatles will really make me learn guitar one day",
  "finished reading norwegian wood. i feel nothing rn. it made me happy, it made me sad. melancholic. depressing even. it was the most intense piece of writing i have read since the kite runner. related to a protagonist since a long time. last time was dostoevsky. idk. masterpiece",
  "not a single significant oscar to dune 2 and anora got 5. fkin rigged as always",
  "woke up to 10k. thank you. time for ama",
  "operations research is the most boring subject ever",
  "real wealth is in buying hardcovers",
  "kaabe ka ehteraam bhi meri nazar mein hai,\nsar kis taraf jhukaun tujhe dekhne ke baad",
  "i really want to do this in india",
  "chatgpt getting really good at writing prose",
  "asked chatgpt to pretend it’s me and write diary entries and the entries are eerily similar to mine",
  "murakami is altering my brain chemistry",
  "RT @WarnerTeddy: I built my first CNC machine when I was 13 years old.\n\nIt led me to pick up my first job at a makerspace, pursue an onslau…",
  "new side quest",
  "read bajirao - the warrior peshwa by e. jaiwant paul. it was fun and informative. \n\nbajirao is really underrated. he truly was the greatest military general of india",
  "they don't make good romcoms anymore",
  "its really hard to quantify the economic impact of certain pieces of technology. eg. google search is something ubiquitous in our life but we cant correlate it with gdp growth even though it contributed a lot to our personal productivity. same with ai chatbots",
  "satya talks a lot like gates",
  "they really brought lilith from evangelion to life",
  "Göbekli Tepe is the most insane lore drop of all time",
  "reason why shakespeare is the goat",
  "create a monopoly on yourself",
  "chhaava was excellent. the cinematography was top notch. especially loved the sangameswar battle sequence. worth the watch on the big screen",
  "",
  "need this in india so bad",
  "a sort of tpot daily newspaper, filled with posts from all the imp blogs. acx, noahopinion, pirate wires, capital gains, works in progress(stripe press), bismarck analysis, construction physics, beansandbytes, core memory etc",
  "",
  "new gpt4o is so good. sonnet3.5 has a real competitor now",
  "history is so nuanced. you need to read books worth of context to understand its subtleties",
  "keeping traditional day on valentines is a very strategic decision by my college",
  "nehru chose socialism and LKY chose capitalism and it made all the difference",
  "damn. got featured in the tech bro podcast",
  "i think google colab had more impact on developer productivity than \"gemini\"",
  "thinking about this timeline",
  "watching interstellar in the theatre was a spiritual and emotional experience. makes me cry everytime. they should re-release it every year",
  "masa son taking a stroll in the stargate",
  "behind the scenes of anthropic’s new model",
  "agi is when @natfriedman stops hiring humans for his side-quests",
  "",
  "near index\n\nnvda, net, pltr, meta",
  "we are like subhadra teaching abhimanyu the chakravyu in her womb - training AI to reach superintelligence but going silent on alignment. hope we are not the ones trapped in the end",
  "bits goa was underwhelming \n\nthe hackathon was a huge disappointment",
  "love watching sonnet3.5 one-shotting r1",
  "claude sonnet 3.5 ilysm",
  "r1 is thinking in one tab, o1-mini is thinking in another tab and sonnet is down in the other tab",
  "new side quest",
  "niti aayog should aspire to be like elon’s DOGE",
  "who is the cto of openai rn?",
  "it must be fun to have roommates who work in opposing ai labs",
  "there is a billionaire behind every successful president",
  "openai was started by billionaires, deepmind is backed by a trillion dollar org and deepseek is backed by a hedge fund",
  "TIL nehru and churchill studied at the same school",
  "deep seeker",
  "another week, another post",
  "books and teenage engineering products are the only things worth overspending on",
  "we let him down",
  "my first tharoor",
  "was discussing with r1 about agi and global gdp and it mentions gpt-10 out of nowhere lol",
  "ep.2 was also really good. interesting insights about bushido and the importance of oil",
  "custom instructions is getting root access to the model's personality",
  "this was one of the most engaging convos i had in a while",
  "best work/book on nehru's pm era ?",
  "seeing lots of weird stuff lately. dog with no tail, cow with five legs etc",
  "sonnet3.5 is not a distilled model which many believed",
  "all warrior codes are hypocritical",
  "lpp is boring as hell",
  "saga would be a great name for anthro's reasoning model",
  "need terence tao to vibe-check r1",
  "my classmates are using deepseek and dont even know what claude is lol",
  "this is one of the best sci-fi short story i have read in a while. its like “her” meets pantheon level stuff",
  "united states of anthropic",
  "RT @karpathy: I don't have too too much to add on top of this earlier post on V3 and I think it applies to R1 too (which is the more recent…",
  "a texas instrument executive’s decision to not promote a person led to one of the biggest geopolitical crises of 21st century",
  "deepseek’s r1 reminds me of isro’ mangalyaan project (in terms of budget comparison to their respective contemporary projects)",
  "kala ghoda arts festival 2025",
  "design methods it is",
  "oppenheimer pilled",
  "currently in a nightout with the homies and we were trauma dumping, talking about regrets and the below mentioned “never asking out that girl” is common theme in most cases",
  "help me select an elective",
  "travis scott performing in india?!!!!!",
  "oai cpo kevin weil said that they are already training o4 right now, during the wsj interview",
  "everything is going according to the plan",
  "",
  "drafting plans for how a DOGE like entity for indian government would look like",
  "reminder to document your readings and viewings",
  "Sarah Paine EP 1: The War For India, lecture and interview was really good. \n\n@dwarkesh_sp doing a really good job with such initiatives. \n\ni can see one day these lectures and interviews evolving into documentaries",
  "imagining an alternate universe where the chatgpt moment happened in 2017/18, just after the attention paper",
  "LOOK AT HIM. THAT'S MY QUANT",
  "the documentary was really good. highly recommend watching if you are interested in the history of deepmind",
  "testing the surf browser, made by @detahq. its really cool",
  "demis giving gendo ikari vibes from that window",
  "started dreaming about ai alignment and mech interp",
  "i need to outsource my twitter scrolling to claude",
  "i had this saved from aaron swartz's site couple of years back",
  "officially started the club and conducted the orientation. onwards to infinity",
  "they made a sequel to the alphago documentary!!",
  "never fails to amaze me",
  "where can i watch this discussion? @dwarkesh_sp @jasoncrawford",
  "founders fund's portfolio consists of the most important startups in all the fields",
  "francois saw o3 and created ndea",
  "really fun build",
  "apple \nteenage engineering \ndyson\nmuji\nikea\nnike\nbraun(rams era)",
  "cowen's school emphasizes studying progress -  it’s introspective and diagnostic \n\nthiel’s school prioritizes acting - zero-to-one creation, risk-taking and directly building the future\n\nboth are important",
  "more startups should do this (independent publishing house)",
  "with great flow states, comes great responsibility",
  "neuralink with google docs api so i can write while sleeping",
  "its funny how @AmandaAskell's call for a partner is mentioned in roots of progress' newsletter under \"other opportunities\"",
  "starting intermittent fasting from today",
  "flow states are fkin amazing",
  "new protocol for decentralised ai model training",
  "blr, 2022",
  "2025 is off to a great start",
  "superintelligence will feel like going from fire to fusion",
  "insane how fast weeks pass by",
  "so used to condensing my thoughts into twitter char limit that writing long form has become tedious",
  "any good contra on @tylercowen’s opinion on ai’s impact on economic growth?",
  "steve’s notes on his speech at palo alto high school",
  "chatgpt search is so much better than perplexity",
  "RT @naklecha: today, i'm excited to release a reinforcement learning guide that carefully explains the intuition and implementation details…",
  "incendies is the most disturbing movie i have ever seen",
  "its insane that i can tweet this every month and it will still be true",
  "new rabbit hole",
  "learning how the computers work at transistor level is so fun",
  "this is where i post from",
  "",
  "borderline agi - superhuman in narrow tasks, primitive generality",
  "currently reading wings of fire by dr. apj abdul kalam",
  "read siddhartha yesterday. i have no words to describe this book. one of the best i have ever read",
  "adverts used to be brilliant",
  "trying this since last month and it has really improved my experience with chatgpt",
  "welch labs made a video on mech interp",
  "the last line cracks me up",

--- END STYLE ---

Tweet to Reply To:
--- START TWEET ---
The heat death of the universe is unacceptable. We need to address entropy in a meaningful way within the next 10^100 years.

@garrytan
--- END TWEET ---

Generated Reply:"""
response = client.models.generate_content(
    model="gemini-2.5-pro-exp-03-25", contents=INSTRUCTION_TEMPLATE
)
print(response.text)
