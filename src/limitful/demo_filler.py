"""The long stretches of the made-up days: talks on stage and visitors at the stand.

A real day with a pendant is hours of speech, not a handful of short chats, so
the demo days need hours of it too. Nobody could write that much by hand, so
these lines are put together from parts: a sentence frame and the words that fit
it. The same seed always gives the same lines. Like the rest of the demo, all of
it is invented.
"""

from __future__ import annotations

import itertools
import random

# A sentence someone on stage might say, and the words that can go in each gap.
STAGE = [
    ("{0} of our vans left the depot less than {1} full last year.",
     ["A third", "A quarter", "Nearly half", "One in five"], ["half", "two thirds", "three quarters"]),
    ("We cut {0} by {1} percent, and nobody out on the road noticed the difference.",
     ["fuel use", "empty miles", "overtime", "late drops", "failed deliveries"], ["six", "nine", "eleven", "fourteen", "eighteen"]),
    ("When {0}, the plan you made last night is already wrong.",
     ["a van breaks down at seven", "a driver calls in sick", "the motorway closes", "a customer moves their window",
      "the weather turns", "the first order of the day is cancelled"]),
    ("Our drivers know {0} better than any map does.",
     ["the back streets", "which loading bays are blocked", "where you can stop for two minutes",
      "which customers are never in", "which gates are locked after four"]),
    ("{0} is the number I would put on the wall of every depot.",
     ["Cost per drop", "Drops per hour", "First-attempt success", "Miles per parcel", "Minutes at the kerb", "Vans home on time"]),
    ("If you only measure {0}, you will get {1}.",
     ["speed", "cost per mile", "vans on the road", "on-time departures"],
     ["tired drivers", "angry customers", "full vans and late bread", "a very fast wrong answer"]),
    ("It took us {0} to trust the software and {1} to stop checking it.",
     ["three months", "a full quarter", "most of a year", "six weeks"], ["a week", "a year", "another month", "one bad winter"]),
    ("Customers will forgive {0}. They will not forgive {1}.",
     ["a late delivery", "a missed window", "one bad week", "a damaged box"],
     ["being told nothing", "the same mistake twice", "a van that never shows", "finding out from the driver"]),
    ("Electric vans change the question from {0} to {1}.",
     ["how far", "how fast", "how cheap"],
     ["where do we charge", "which round ends near a charger", "how heavy is the load", "who plans the charging"]),
    ("We moved {0} from the afternoon to the morning and saved {1} a week.",
     ["the heavy drops", "the city-centre round", "the returns", "the school deliveries"],
     ["forty hours", "two vans", "a full shift", "nine hundred miles"]),
    ("Nobody joins this industry to {0}.",
     ["fill in a spreadsheet at midnight", "phone forty customers about a delay", "plan a round again by hand",
      "argue with a sat nav", "explain the same late van three times"]),
    ("The question from the board is always the same: {0}",
     ["what does it save?", "how soon does it pay back?", "what breaks if we switch it off?", "who else is using it?",
      "why didn't we do this before?"]),
    ("A good depot manager can plan {0} vans by hand. Past that, {1}.",
     ["ten", "fifteen", "twenty", "thirty"],
     ["it is guesswork", "something always gets missed", "they stop sleeping", "the plan is the same every day whether it fits or not"]),
    ("In {0}, the hard part was not the software. It was {1}.",
     ["our first trial", "the northern region", "year one", "the roll-out"],
     ["the address data", "getting drivers to trust it", "the handheld devices", "agreeing what a late delivery means"]),
    ("Think about {0}. {1}.",
     ["a wet Monday in January", "the week before a holiday", "the first hot day of summer", "a strike on the railways"],
     ["Every plan you have is tested at once", "Volumes double and nobody told the depot",
      "That is when the model earns its keep", "The phones start before the vans do"]),
    ("We now give customers {0}, and complaints fell by {1}.",
     ["a live arrival time", "the driver's position", "a one-hour window", "a photo at the door"],
     ["a third", "half", "a fifth", "more than we expected"]),
    ("Cold chain has one rule that beats all the others: {0}.",
     ["the door stays shut", "frozen comes off last", "no van waits in the sun", "the clock starts at loading",
      "nobody guesses a temperature"]),
    ("Every {0} we remove gives {1} back to a driver.",
     ["failed drop", "wrong address", "double-parked stop", "wait at a goods-in desk"],
     ["ten minutes", "a lunch break", "a calmer afternoon", "part of the evening"]),
    ("People ask me about {0}. My honest answer is {1}.",
     ["drones", "driverless vans", "robots on the pavement", "delivery within the hour"],
     ["not this decade", "ask me in five years", "only where the numbers work", "it matters less than tidy addresses"]),
    ("The data we needed was already there, in {0}. Nobody had {1}.",
     ["the handhelds", "the fuel cards", "the tachographs", "the customer service log"],
     ["looked at it", "joined it up", "asked the drivers what it meant", "kept more than a month of it"]),
    ("{0} costs us more than {1}, and it never appears on a report.",
     ["Waiting at goods-in", "Driving back empty", "The second attempt", "Parking", "A wrong postcode"],
     ["fuel", "tyres", "overtime", "insurance"]),
    ("Our best depot and our worst depot have {0}. The difference is {1}.",
     ["the same vans", "the same software", "the same customers", "the same roads"],
     ["the planning", "who answers the phone", "how the vans are loaded", "ten minutes at the start of the day"]),
    ("I would rather have {0} than {1}.",
     ["a plan that is roughly right at six", "tidy addresses", "one honest number", "drivers who complain out loud"],
     ["a perfect one at nine", "a cleverer algorithm", "a dashboard with forty", "silence"]),
    ("Start with {0}. It is small enough to fix and big enough to {1}.",
     ["one depot", "one round", "one customer", "the returns"],
     ["prove the point", "show the board", "annoy the right people", "pay for the next step"]),
    ("By {0}, we expect {1} of our city deliveries to be made without diesel.",
     ["next year", "2028", "the end of the decade"], ["a third", "half", "most", "nearly all"]),
    ("The driver shortage is really {0}.",
     ["a planning problem", "a problem of bad shifts", "about the last two hours of the day", "a problem we made ourselves"]),
    ("We lose {0} a day per van to {1}.",
     ["twenty minutes", "half an hour", "forty minutes", "nearly an hour"],
     ["looking for parking", "waiting to be let in", "wrong addresses", "loading in the wrong order"]),
    ("Loading order sounds dull until you watch a driver {0}.",
     ["empty half the van to reach one box", "climb over pallets in the rain", "deliver the last stop first",
      "lose ten minutes at every door"]),
    ("What surprised us most was {0}.",
     ["how little the routes changed", "how quickly drivers took to it", "that the savings came from the small depots",
      "that customers noticed before finance did", "how wrong our own addresses were"]),
    ("You cannot plan around {0} if nobody writes it down.",
     ["a school gate at three", "a market day", "a low bridge", "a customer who is only in on Tuesdays",
      "a loading bay that shuts at noon"]),
    ("Our rule is simple: {0}.",
     ["no driver finishes late two days running", "every late drop gets a phone call", "the plan is frozen at five",
      "the driver can always overrule the route"]),
    ("Margins in {0} are about {1} percent, so a small saving is the whole profit.",
     ["parcel delivery", "food distribution", "chilled transport", "the last mile"], ["two", "three", "four"]),
    ("The first winter with the new system, {0}.",
     ["we had our fewest late drops in ten years", "snow closed two depots and the plan coped",
      "we still got it wrong on the first icy morning", "the phones stayed quiet for once"]),
    ("Ask your drivers {0}. The answer will tell you {1}.",
     ["what they would change", "which stop they dread", "where they lose time", "what the plan gets wrong"],
     ["more than a consultant will", "where to start", "what your data is missing", "why people leave"]),
    ("There is no point saving {0} if it costs you {1}.",
     ["five miles", "ten minutes", "a van", "a few litres of fuel"],
     ["a customer", "a driver", "a missed window", "the trust of the depot"]),
    ("We send {0} to every depot each Monday, and it changed the conversation.",
     ["the league table", "cost per drop", "the late list", "the fuel figures"]),
]

# What a visitor asks, the words that fit the gap, and ways of answering.
QUESTIONS = [
    ("Does it handle {0}?",
     ["driver breaks", "time windows", "return collections", "two-person crews", "vehicle height limits", "mixed loads",
      "rounds that take two days", "drivers who start from home"],
     ["Yes. You set that once for the depot and every plan respects it.",
      "It does. That was one of the first things customers asked us for.",
      "Yes, and you can change it for a single day if you need to."]),
    ("What happens when {0}?",
     ["a driver ignores the route", "a van breaks down mid-morning", "an order comes in after the plan is made",
      "a customer cancels at the last minute", "a driver is running late", "two drivers swap vans"],
     ["It plans the rest of the day again in a few seconds and tells the drivers it affects.",
      "Nothing dramatic. It offers a new plan, and you choose whether to take it.",
      "The dispatcher sees two options, and one tap sends the change to the handhelds."]),
    ("How long does it take to {0}?",
     ["set up a depot", "train a dispatcher", "plan a hundred vans", "bring in our customer list", "see a saving"],
     ["Less than people expect. Most of the time goes on cleaning up addresses.",
      "Days, not months. We do the first one alongside your own team.",
      "For a fleet your size, about a week from the start to a first plan."]),
    ("Can it read orders from {0}?",
     ["a spreadsheet", "our order system", "our warehouse software", "a plain file every night", "the system we invoice from"],
     ["Yes. A file every night is how most customers start.",
      "It can. If it comes out as rows and columns, we can read it.",
      "Yes, and Nadia can show you that screen if you like."]),
    ("We tried {0} two years ago and the drivers hated it. Why would this be different?",
     ["route planning", "a different planner", "something like this", "a system from our vehicle supplier"],
     ["Usually because nobody asked the drivers. Ours lets them flag a bad stop, and the plan learns from it.",
      "Fair question. We start with one round and the drivers who volunteer.",
      "Because the driver can always overrule it, and we look at every time they do."]),
    ("Is the price per {0}?",
     ["van", "driver", "depot", "route", "person using it"],
     ["Per vehicle on the main plan, per route on the starter plan.",
      "It depends on the size of the fleet. I can send you both price lists.",
      "Per vehicle, billed monthly, and you can drop vans in the quiet season."]),
    ("Do the drivers need {0}?",
     ["a new handheld", "their own phones", "a signal all day", "training", "to log in every morning"],
     ["No. It runs on the phones or handhelds you already have.",
      "Only a short walk-through. Most pick it up on the first round.",
      "It keeps working without a signal and catches up later."]),
    ("How does it cope with {0}?",
     ["city-centre access rules", "country rounds with long gaps", "narrow streets", "school traffic", "ferry timetables",
      "low-emission zones"],
     ["You draw the rule on the map once and the planner stays inside it.",
      "Better than most. It learns real drive times from your own vans.",
      "That's where planning by hand struggles most, and where we tend to save the most time."]),
    ("Who else in {0} uses it?",
     ["food distribution", "parcels", "chilled transport", "building supplies", "pharmacy delivery"],
     ["A few I can name and a few I can't. I'll send you two who have agreed to take calls.",
      "Several regional fleets. The closest to you is about your size.",
      "Enough that we know the awkward parts. I can put you in touch with one."]),
    ("Where is our data kept, and {0}?",
     ["who can see it", "can we get it back out", "for how long", "is it used for anything else"],
     ["In the region you choose, and only your own people can see it.",
      "It's yours. You can take a full copy out at any time.",
      "We have a short document on exactly that. I'll send it over."]),
    ("Could we try it on {0} first?",
     ["one depot", "a single round", "last month's orders", "our quietest day"],
     ["Yes, that's how nearly everyone starts.",
      "Of course. Send us a month of orders and we'll show you what it would have planned.",
      "We'd recommend it. It gives you real numbers before you commit."]),
    ("Does it plan {0} as well?",
     ["the loading order", "driver shifts", "charging stops for electric vans", "collections on the way back",
      "which van goes where tomorrow"],
     ["Yes, as part of the same plan.",
      "It does, though most people switch that on in the second month.",
      "That's on the larger plan. Nadia can show you how it looks."]),
    ("What do you need from us to {0}?",
     ["give a quote", "run a test", "get started", "show a saving"],
     ["The size of the fleet, the depots, and a typical week of orders.",
      "A sample of your orders and half an hour with whoever plans today.",
      "Very little. A file of stops and a list of your vehicles."]),
    ("Our planner has done the routes for {0} years. What do I tell {1}?",
     ["ten", "fifteen", "twenty", "thirty"], ["him", "her", "them"],
     ["That it takes the dull half of the job and leaves the judgment.",
      "That they'll be the one deciding when to overrule it.",
      "Bring them to the demo. Planners usually become the keenest users."]),
    ("How accurate are the {0}?",
     ["arrival times", "drive times", "fuel estimates", "savings you quote"],
     ["Within a few minutes, once it has a fortnight of your own data.",
      "They start reasonable and get better each week.",
      "We show you predicted against actual, so you can judge for yourself."]),
    ("Can a customer {0}?",
     ["see where their delivery is", "change their window", "get a text before we arrive", "leave instructions for the driver"],
     ["Yes, if you turn it on. Most do after the first month.",
      "They can, and it cuts the phone calls a lot.",
      "Yes. You choose what they see."]),
    ("Is there a contract, or {0}?",
     ["can we leave when we like", "is it month to month", "do we pay up front", "is there a minimum term"],
     ["Month to month on the starter plan, yearly on the main one.",
      "A year is normal, with a way out after the test period.",
      "Nothing ties you in for the first three months."]),
    ("Does it work alongside {0}?",
     ["our vehicle trackers", "the handheld software we have", "our customer website", "our fuel cards"],
     ["Usually, yes. Tell me which one and I'll check tonight.",
      "It does with most of them, and we add more each quarter.",
      "Yes. Live positions make the arrival times a good deal better."]),
]

# What the people on the stand ask a visitor, and ways a visitor answers.
DISCOVERY = [
    ("How do you plan the routes today?",
     ["By hand, the night before.", "A spreadsheet that one person understands.", "Our transport manager does it from memory.",
      "We have a planner, but it's old and nobody trusts it."]),
    ("How many drops does a van do on a normal day?",
     ["About forty.", "Sixty in town, half that in the country.", "It varies a lot. That's part of the problem.",
      "Around eighty, small ones."]),
    ("What made you stop at our stand?",
     ["The fuel number on your screen.", "A colleague told me to.", "We're looking at suppliers this year.",
      "Honestly, I was walking past, but now I'm curious."]),
    ("What goes wrong most often?",
     ["Late starts. The vans leave after the traffic has built up.", "Addresses. We lose time at the door.",
      "Too many vans going to the same part of town.", "Drivers finishing late, and then leaving us."]),
    ("Are you tied to a supplier at the moment?",
     ["Until the spring.", "No. It's all done by hand.", "Until next year, but we'd move sooner for the right thing.",
      "I'd have to check."]),
    ("Who else would need to agree to it?",
     ["Finance, and whoever runs the depots.", "Just me and the owner.", "Our IT people, mainly.",
      "The transport manager. He's here somewhere."]),
    ("Do your drivers keep the same round every day?",
     ["Mostly. They'd riot if we changed it.", "No, it moves with the orders.", "The older ones do.",
      "In town, yes. Out of town it changes daily."]),
    ("What would a good result look like for you?",
     ["One van fewer on the road.", "Drivers home on time.", "Fewer phone calls about late deliveries.",
      "A fuel bill that stops climbing."]),
]

INTROS = [  # business, fleet, sites, fleet in lower case
    "We're a {0} with {3} vans, working out of {2}.",
    "I look after transport for a {0}. {1} vans, {2}.",
    "Hello. {1} vans, {2}, and we're a {0}.",
]
BUSINESSES = ["dairy", "flower wholesaler", "pharmacy wholesaler", "furniture maker", "brewery", "laundry service",
              "frozen food distributor", "parcel carrier", "builders' merchant", "catering supplier",
              "fruit and vegetable wholesaler", "pet food company", "bottled water supplier", "office supplies firm"]
FLEETS = ["Eight", "Twelve", "Fifteen", "Eighteen", "Thirty", "Forty-five", "Sixty", "Ninety"]
SITES = ["one depot", "two depots", "three sites"]
GREETINGS = ["Welcome. What would you like to see?", "Good to meet you. Shall I show you a day's plan?",
             "Thanks for stopping. What are you hoping to fix?", "Hello. Have a look at the screen while we talk.",
             "Nice to meet you. That's a size we see a lot.", "Come in. Nadia has the demo running."]
FOLLOW = ["That's better than I expected.", "Good, that was my worry.", "Our current system can't do that.",
          "I'd need to see it with our own data.", "Makes sense.", "Right. That's what I hoped you'd say.",
          "Interesting. Nobody else here has said that.", "Fine. That answers it."]
CLOSINGS = ["Can you send me the pricing?", "Scan my badge and send me something to read.",
            "I'll bring my transport manager by later.", "Let me think about it. Do you have a card?",
            "That's useful. I'll be in touch after the show."]
FAREWELLS = ["Of course. You'll have it tonight.", "Will do. Thanks for stopping.", "Please do. We're here until five.",
             "Here you go. My email is on it."]


def _all(frame: str, *gaps: list[str]) -> list[str]:
    return [frame.format(*words) for words in itertools.product(*gaps)]


class Filler:
    """Writes lines to fill a stretch of time. Each line is (speaker, text, start_ms, end_ms)."""

    def __init__(self, seed: str = "limitful demo") -> None:
        self.rng = random.Random(seed)
        self._sentences: list[tuple[int, str]] = []  # (which frame, the sentence)
        # One list of (question, answers) for each frame.
        self._questions = [[(q, answers) for q in _all(frame, *gaps)] for frame, *gaps, answers in QUESTIONS]
        self._answered: list[str] = []  # the last few answers given, so none comes straight back

    def _say(self, lines: list, who: str, text: str, at: int | None, per_word: int, end: int) -> int | None:
        """Add a line starting at `at`. Returns when it ends, or None if it would run past `end`."""
        if at is None:
            return None
        done = at + 900 + per_word * len(text.split())
        if done > end:
            return None
        lines.append((who, text, at, done))
        return done

    def _sentence(self, used: set[str], lately: list[int]) -> str:
        """The next sentence for a talk: not one it has had, and not shaped like the last few."""
        if len(self._sentences) < 60:
            more = [(n, s) for n, (frame, *gaps) in enumerate(STAGE) for s in _all(frame, *gaps)]
            self.rng.shuffle(more)
            self._sentences = more + self._sentences  # sentences are taken from the end
        for back in range(1, len(self._sentences) + 1):
            frame, text = self._sentences[-back]
            if text not in used and frame not in lately:
                del self._sentences[-back]
                break
        else:
            frame, text = self._sentences.pop()
        used.add(text)
        lately.append(frame)
        del lately[:-14]
        return text

    def talk(self, speakers: list[str], start: int, end: int) -> list:
        """People on stage, one speaking at a time, with the odd pause."""
        rng = self.rng
        lines: list = []
        used: set[str] = set()
        lately: list[int] = []
        who, at = speakers[0], start
        while True:
            done = self._say(lines, who, self._sentence(used, lately), at, 640, end)
            if done is None:
                return lines
            at = done + (int(rng.uniform(20_000, 50_000)) if rng.random() < 0.03 else int(rng.uniform(500, 3000)))
            if len(speakers) > 1 and rng.random() < 0.25:
                who = rng.choice([s for s in speakers if s != who])

    def _exchange(self, lines: list, asker: str, hosts: list[str], text: str, answers: list[str],
                  at: int | None, end: int) -> int | None:
        rng = self.rng
        at = self._say(lines, asker, text, at, 430, end)
        if at is None:
            return None
        answer = rng.choice([a for a in answers if a not in self._answered] or answers)
        self._answered = (self._answered + [answer])[-8:]
        at = self._say(lines, rng.choice(hosts), answer, at + int(rng.uniform(400, 1500)), 430, end)
        if at is not None and rng.random() < 0.3:
            follow = rng.choice([f for f in FOLLOW if f not in self._answered])
            self._answered = (self._answered + [follow])[-8:]
            at = self._say(lines, asker, follow, at + int(rng.uniform(400, 1500)), 430, end)
        return at

    def stand(self, hosts: list[str], start: int, end: int, visitor: str = "Visitor") -> list:
        """One visitor after another at a trade-show stand, with lulls in between."""
        rng = self.rng
        lines: list = []
        at: int | None = start
        while at is not None:
            fleet = rng.choice(FLEETS)
            intro = rng.choice(INTROS).format(rng.choice(BUSINESSES), fleet, rng.choice(SITES), fleet.lower())
            at = self._say(lines, visitor, intro, at, 430, end)
            at = self._say(lines, rng.choice(hosts), rng.choice(GREETINGS), at and at + 900, 430, end)
            # A few questions, each of a different kind, and usually one asked back by the stand.
            asked = [(visitor, hosts, *rng.choice(kind)) for kind in rng.sample(self._questions, rng.randint(3, 6))]
            if rng.random() < 0.7:
                asked.insert(rng.randint(0, 2), (rng.choice(hosts), [visitor], *rng.choice(DISCOVERY)))
            for asker, others, text, answers in asked:
                at = self._exchange(lines, asker, others, text, answers, at and at + int(rng.uniform(1500, 7000)), end)
            at = self._say(lines, visitor, rng.choice(CLOSINGS), at and at + 2000, 430, end)
            at = self._say(lines, rng.choice(hosts), rng.choice(FAREWELLS), at and at + 800, 430, end)
            at = at and at + int(rng.uniform(10_000, 60_000))
        return lines

    def questions(self, asker: str, hosts: list[str], start: int, end: int) -> list:
        """One person working through their questions: none twice, and no two of a kind in a row."""
        rng = self.rng
        lines: list = []
        at: int | None = start
        kinds = [rng.sample(kind, len(kind)) for kind in self._questions]
        while at is not None and any(kinds):
            for kind in rng.sample(kinds, len(kinds)):
                if kind and at is not None:
                    at = self._exchange(lines, asker, hosts, *kind.pop(), at, end)
                    at = at and at + int(rng.uniform(2000, 9000))
        return lines
