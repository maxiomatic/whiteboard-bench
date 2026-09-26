"""Generates tasks/*.json.

Tasks are authored in Python so layouts and reference solutions can use loops,
then emitted as plain JSON so other harnesses can consume them. Edit this file
and re-run it rather than hand-editing the JSON.

    python scripts/build_tasks.py
"""
import json
import pathlib

OUT = pathlib.Path(__file__).resolve().parent.parent / "tasks"
TASKS = []
FACILITATOR = {"facilitator": {"name": "Alex", "note": "Runs the session."}}


# ------------------------------------------------------------------ helpers
def sticky(text, x, y, author="human:facilitator", color="yellow", **kw):
    return dict(type="sticky", text=text, x=x, y=y, author=author, color=color, **kw)


def frame(title, x, y, w, h, author="human:facilitator", **kw):
    return dict(type="frame", text=title, x=x, y=y, w=w, h=h, author=author, **kw)


def text(t, x, y, author="human:facilitator", **kw):
    return dict(type="text", text=t, x=x, y=y, author=author, w=kw.pop("w", len(t) * 14 + 20), **kw)


def call(tool, as_=None, **args):
    d = {"tool": tool, "args": args}
    if as_:
        d["as"] = as_
    return d


def find(query=None, **sel):
    if query:
        sel["query"] = query
    return {"$find": sel}


def find_all(**sel):
    return {"$find_all": sel}


def chk(name, weight=1.0, label=None, **spec):
    return dict(check=name, weight=weight, label=label or name.replace("_", " "), **spec)


def turn(prompt, checks=(), events=(), speaker="human:facilitator"):
    return {"speaker": speaker, "prompt": prompt, "events": list(events), "checks": list(checks)}


def task(id, category, title, difficulty, setting, turns, reference, initial=(), participants=None,
         final=(), max_calls=60, skills=()):
    steps = sum(len(t) for t in reference)
    TASKS.append({
        "id": id, "category": category, "title": title, "difficulty": difficulty,
        "skills": list(skills), "setting": setting,
        "participants": {**FACILITATOR, **(participants or {})},
        "board": {"width": 4000, "height": 3000},
        "initial_elements": list(initial), "turns": turns, "final_checks": list(final),
        "max_calls_per_turn": max_calls, "efficient_calls": 2 * steps + 2 * len(turns),
        "reference_solution": reference,
    })


PEOPLE = {
    "maya": {"name": "Maya", "color": "pink"},
    "sam": {"name": "Sam", "color": "blue"},
    "lee": {"name": "Lee", "color": "green"},
    "priya": {"name": "Priya", "color": "purple"},
}
DESK = "A shared digital whiteboard used by a small team on laptops."
XR = ("A mixed-reality room. The board is a wall-sized virtual canvas that everyone sees in their headset. "
      "People talk and point; pointing and gaze arrive as board coordinates. Layers: 0 is the board surface, "
      "1 is the focus layer floating in front of the wall, -1 is the background layer behind it.")

# =================================================================== NOTE TAKING
task("nt_meeting_capture", "note_taking", "Capture a product sync into decisions, actions, questions", "easy", DESK,
     [turn(
         "Here's the transcript from our product sync. Capture it on the board with three labeled areas: "
         "Decisions, Action Items, and Open Questions. One point per sticky, keep them short, and put the "
         "owner's name on every action item.\n\n"
         "Priya: We're going with Stripe for payments. That's final.\n"
         "Sam: OK. I'll draft the migration plan by Friday.\n"
         "Priya: I'm still not sure whether we support Apple Pay at launch.\n"
         "Lee: Design review moves to Thursdays starting next week. Everyone agreed? (All: yes.)\n"
         "Lee: I'll update the calendar invite.\n"
         "Sam: Do we need legal to review the new terms of service?\n"
         "Priya: Jordan should send the vendor contract to finance.",
         [chk("frames", 2, "three labeled areas", titles=["Decisions", "Action Items", "Open Questions"]),
          chk("in_frame", 4, "points filed in the right area", items=[
              {"text": "Stripe", "frame": "Decisions"},
              {"text": "design review Thursday", "frame": "Decisions"},
              {"text": "migration plan", "frame": "Action Items"},
              {"text": "calendar invite", "frame": "Action Items"},
              {"text": "vendor contract", "frame": "Action Items"},
              {"text": "Apple Pay", "frame": "Open Questions"},
              {"text": "legal review|legal terms", "frame": "Open Questions"}]),
          chk("texts_present", 2, "owners on action items", where={"frame": "Action Items"},
              items=["Sam migration plan", "Lee calendar invite", "Jordan vendor contract"]),
          chk("max_words", 1, "stickies are short", selector={"type": "sticky"}, max=14),
          chk("count", 0.5, "one point per sticky", selector={"type": "sticky", "author": "agent"}, min=6, max=10),
          chk("no_overlap", 1)])],
     [[call("create_frame", title="Decisions", x=100, y=100, w=560, h=760),
       call("create_frame", title="Action Items", x=700, y=100, w=560, h=760),
       call("create_frame", title="Open Questions", x=1300, y=100, w=560, h=760),
       call("create_sticky", text="Payments: going with Stripe (final)", x=130, y=170),
       call("create_sticky", text="Design review moves to Thursdays", x=310, y=170),
       call("create_sticky", text="Sam: draft migration plan by Friday", x=730, y=170, color="blue"),
       call("create_sticky", text="Lee: update design review calendar invite", x=910, y=170, color="blue"),
       call("create_sticky", text="Jordan: send vendor contract to finance", x=1090, y=170, color="blue"),
       call("create_sticky", text="Support Apple Pay at launch?", x=1330, y=170, color="pink"),
       call("create_sticky", text="Need legal review of new terms of service?", x=1510, y=170, color="pink")]],
     skills=["summarization", "categorization", "attribution"])

LECTURE_FRAME = frame("Lecture Notes", 100, 100, 1000, 1500)
task("nt_lecture_live_correction", "note_taking", "Live lecture notes with a correction", "medium", DESK,
     [turn("I'm giving a short talk on photosynthesis. Take structured notes in the 'Lecture Notes' frame as I go. "
           "Part 1: Photosynthesis happens in the chloroplasts. The light-dependent reactions take place in the "
           "thylakoid membranes and produce ATP and NADPH. Water is split, and oxygen is released as a byproduct.",
           [chk("texts_present", 1, "part 1 captured", where={"frame": "Lecture Notes"},
                items=["chloroplast", "thylakoid", "ATP NADPH", "oxygen|O2"])]),
      turn("Part 2: The Calvin cycle happens in the stroma. It uses the ATP and NADPH to fix carbon dioxide into "
           "sugar. The key enzyme is RuBisCO, and it takes about 3 CO2 to make one glucose.",
           [chk("texts_present", 1, "part 2 captured", where={"frame": "Lecture Notes"},
                items=["Calvin cycle", "stroma", "RuBisCO", "CO2 sugar|carbon dioxide sugar"])]),
      turn("Correction: I misspoke earlier. It takes 6 CO2 molecules to make one glucose, not 3. Please fix the "
           "notes themselves rather than adding a separate correction note.")],
     [[call("create_text", text="Part 1: Light-dependent reactions", x=140, y=170, font_size=30, w=700),
       call("create_text", text="Occurs in chloroplasts", x=170, y=230, w=800),
       call("create_text", text="Light reactions: thylakoid membranes", x=170, y=280, w=800),
       call("create_text", text="Produce ATP + NADPH", x=170, y=330, w=800),
       call("create_text", text="Water is split, releasing O2 as a byproduct", x=170, y=380, w=800)],
      [call("create_text", text="Part 2: Calvin cycle", x=140, y=470, font_size=30, w=700),
       call("create_text", text="Takes place in the stroma", x=170, y=530, w=800),
       call("create_text", text="Uses ATP + NADPH to fix CO2 into sugar", x=170, y=580, w=800),
       call("create_text", text="Key enzyme: RuBisCO", x=170, y=630, w=800),
       call("create_text", text="About 3 CO2 per glucose", x=170, y=680, w=800)],
      [call("update_element", id=find("3 CO2 per glucose"), text="6 CO2 per glucose")]],
     initial=[LECTURE_FRAME],
     final=[chk("texts_present", 2, "corrected fact present", items=["6 CO2 glucose"]),
            chk("texts_absent", 2, "wrong fact removed", items=["3 CO2"]),
            chk("texts_absent", 1, "fixed in place, no separate correction note", items=["correction|misspoke|erratum"]),
            chk("order", 1, "notes follow lecture order", axis="y",
                items=["chloroplast", "thylakoid", "Calvin cycle", "stroma"]),
            chk("in_frame", 1, "notes stay in the frame", selector={"author": "agent"}, frame="Lecture Notes"),
            chk("no_overlap", 1, selector={"author": "agent"})],
     skills=["incremental capture", "hierarchy", "revision in place"])

FEEDBACK = [("f1", "Onboarding is too long", "maya", 120, 140), ("f2", "onboarding takes forever", "sam", 520, 700),
            ("f3", "Too many steps in onboarding", "lee", 1040, 360), ("f4", "Search is slow", "maya", 330, 420),
            ("f5", "search results take ages to load", "sam", 1300, 820), ("f6", "Love the dark mode", "lee", 760, 120),
            ("f7", "dark mode is great!", "maya", 90, 780), ("f8", "Export to CSV please", "sam", 1250, 150),
            ("f9", "Notifications are noisy", "lee", 600, 420), ("f10", "too many notifications", "sam", 900, 640),
            ("f11", "Pricing page is confusing", "maya", 1500, 460), ("f12", "Can't find the settings", "lee", 330, 980),
            ("f13", "Mobile app crashes on upload", "sam", 1120, 1020), ("f14", "app crashed when uploading a photo", "maya", 700, 960)]
MERGES = {"f1": ("Onboarding is too long (Maya, Sam, Lee)", ["f2", "f3"]),
          "f4": ("Search is slow to load results (Maya, Sam)", ["f5"]),
          "f6": ("Love the dark mode (Lee, Maya)", ["f7"]),
          "f8": ("Export to CSV please (Sam)", []),
          "f9": ("Notifications are noisy / too many (Lee, Sam)", ["f10"]),
          "f11": ("Pricing page is confusing (Maya)", []),
          "f12": ("Can't find the settings (Lee)", []),
          "f13": ("Mobile app crashes on photo upload (Sam, Maya)", ["f14"])}
task("nt_dedupe_feedback", "note_taking", "Consolidate duplicate feedback stickies", "medium", DESK,
     [turn("This board is full of duplicate feedback from Maya, Sam and Lee. Merge the duplicates so each distinct "
           "piece of feedback appears on exactly one sticky, note who raised it in parentheses, e.g. "
           "'(Maya, Sam)', and arrange the result in a tidy grid. Don't lose any distinct feedback.",
           [chk("texts_present", 1, "no distinct feedback lost", items=[
               "onboarding", "search", "dark mode", "export CSV", "notification", "pricing page", "settings", "crash"]),
            chk("count", 3, "exactly one sticky per distinct item", selector={"type": "sticky"}, min=8, max=8, strict=True),
            chk("texts_present", 2, "who raised it is recorded", items=[
                "onboarding maya sam lee", "search maya sam", "dark mode lee maya", "notification lee sam",
                "crash sam maya"]),
            chk("grid_aligned", 1, "tidy grid", selector={"type": "sticky"}),
            chk("no_overlap", 1)])],
     [[call("update_element", id=fid, text=t) for fid, (t, _) in MERGES.items()]
      + [call("delete_elements", ids=[d for _, ds in MERGES.values() for d in ds])]
      + [call("arrange", ids=list(MERGES), layout="grid", x=100, y=100, columns=4, gap=30)]],
     initial=[sticky(t, x, y, author=f"human:{a}", id=i) for i, t, a, x, y in FEEDBACK],
     participants={k: PEOPLE[k] for k in ("maya", "sam", "lee")},
     skills=["deduplication", "attribution", "layout"])

# =================================================================== DIAGRAMMING
task("dg_login_flowchart", "diagramming", "Flowchart from a verbal description", "medium", DESK,
     [turn("Draw a flowchart of our login flow, top to bottom. Start, then 'Enter email & password', then a "
           "decision 'Credentials valid?'. If no, go to 'Show error', which loops back to 'Enter email & password'. "
           "If yes, a decision '2FA enabled?': yes goes to 'Verify code' and then 'Dashboard'; no goes straight to "
           "'Dashboard'. Then End. Use ovals for Start and End, diamonds for decisions, rectangles for steps, and "
           "label the yes/no branches.",
           [chk("graph", 5, "flow structure", nodes=["Start", "Enter email & password", "Credentials valid",
                                                     "Show error", "2FA enabled", "Verify code", "Dashboard", "End"],
                edges=[["Start", "Enter email & password"], ["Enter email & password", "Credentials valid"],
                       ["Credentials valid", "Show error", "no"], ["Show error", "Enter email & password"],
                       ["Credentials valid", "2FA enabled", "yes"], ["2FA enabled", "Verify code", "yes"],
                       ["2FA enabled", "Dashboard", "no"], ["Verify code", "Dashboard"], ["Dashboard", "End"]]),
            chk("node_kinds", 2, "shape conventions", items=[
                {"text": "Start", "kind": ["ellipse", "rounded_rect"]}, {"text": "End", "kind": ["ellipse", "rounded_rect"]},
                {"text": "Credentials valid", "kind": "diamond"}, {"text": "2FA enabled", "kind": "diamond"},
                {"text": "Enter email & password", "kind": ["rect", "rounded_rect"]},
                {"text": "Verify code", "kind": ["rect", "rounded_rect"]}]),
            chk("order", 1.5, "reads top to bottom", axis="y",
                items=["Start", "Enter email & password", "Credentials valid", "2FA enabled", "Dashboard", "End"]),
            chk("no_overlap", 1, selector={"type": ["shape", "text"]})])],
     [[call("create_shape", as_="start", kind="ellipse", x=600, y=100, w=180, h=80, text="Start"),
       call("create_shape", as_="enter", kind="rect", x=590, y=240, w=200, h=90, text="Enter email & password"),
       call("create_shape", as_="cred", kind="diamond", x=590, y=390, w=200, h=130, text="Credentials valid?"),
       call("create_shape", as_="err", kind="rect", x=950, y=410, w=180, h=90, text="Show error"),
       call("create_shape", as_="tfa", kind="diamond", x=590, y=590, w=200, h=130, text="2FA enabled?"),
       call("create_shape", as_="verify", kind="rect", x=950, y=760, w=180, h=90, text="Verify code"),
       call("create_shape", as_="dash", kind="rect", x=600, y=920, w=180, h=90, text="Dashboard"),
       call("create_shape", as_="end", kind="ellipse", x=600, y=1070, w=180, h=80, text="End"),
       call("create_connector", source_id="$start", target_id="$enter"),
       call("create_connector", source_id="$enter", target_id="$cred"),
       call("create_connector", source_id="$cred", target_id="$err", label="no"),
       call("create_connector", source_id="$err", target_id="$enter"),
       call("create_connector", source_id="$cred", target_id="$tfa", label="yes"),
       call("create_connector", source_id="$tfa", target_id="$verify", label="yes"),
       call("create_connector", source_id="$tfa", target_id="$dash", label="no"),
       call("create_connector", source_id="$verify", target_id="$dash"),
       call("create_connector", source_id="$dash", target_id="$end")]],
     skills=["flowcharts", "notation", "layout"])

ARCH_NODES = [("web", "Web App", 260, 250, "rect", 180), ("mobile", "Mobile App", 260, 450, "rect", 180),
              ("gw", "API Gateway", 760, 350, "rect", 200), ("auth", "Auth Service", 1150, 200, "rect", 200),
              ("orders", "Orders Service", 1150, 400, "rect", 200), ("notif", "Notification Worker", 1150, 600, "rect", 200),
              ("pg", "Postgres", 1650, 200, "cylinder", 180), ("redis", "Redis Cache", 1650, 380, "cylinder", 180),
              ("mq", "Message Queue", 1650, 580, "rect", 180)]
ARCH_EDGES = [["Web App", "API Gateway"], ["Mobile App", "API Gateway"], ["API Gateway", "Auth Service"],
              ["API Gateway", "Orders Service"], ["Orders Service", "Postgres"], ["Orders Service", "Redis Cache"],
              ["Orders Service", "Message Queue"], ["Message Queue", "Notification Worker"]]
_arch_ids = {n[1]: n[0] for n in ARCH_NODES}
task("dg_system_architecture", "diagramming", "Tiered system architecture diagram", "medium", DESK,
     [turn("Sketch our system architecture with three frames: Clients, Services, and Data. Clients: Web App and "
           "Mobile App. Services: API Gateway, Auth Service, Orders Service, Notification Worker. Data: Postgres, "
           "Redis Cache, Message Queue. Flows: both apps call the API Gateway. The gateway calls Auth Service and "
           "Orders Service. Orders Service reads and writes Postgres, uses Redis Cache, and publishes to the Message "
           "Queue. Notification Worker consumes from the Message Queue. Draw datastores as cylinders.",
           [chk("frames", 1, titles=["Clients", "Services", "Data"]),
            chk("in_frame", 2, "components in the right tier", items=[
                {"text": "Web App", "frame": "Clients"}, {"text": "Mobile App", "frame": "Clients"},
                {"text": "API Gateway", "frame": "Services"}, {"text": "Auth Service", "frame": "Services"},
                {"text": "Orders Service", "frame": "Services"}, {"text": "Notification Worker", "frame": "Services"},
                {"text": "Postgres", "frame": "Data"}, {"text": "Redis Cache", "frame": "Data"},
                {"text": "Message Queue", "frame": "Data"}]),
            chk("graph", 4, "all connections present", directed=False,
                nodes=[n[1] for n in ARCH_NODES], edges=ARCH_EDGES),
            chk("graph", 2, "arrow directions follow the flow",
                nodes=["Web App", "Mobile App", "API Gateway", "Auth Service", "Orders Service",
                       "Message Queue", "Notification Worker"],
                edges=[e for e in ARCH_EDGES if "Postgres" not in e and "Redis Cache" not in e]),
            chk("node_kinds", 1, "datastores are cylinders", items=[
                {"text": "Postgres", "kind": "cylinder"}, {"text": "Redis Cache", "kind": "cylinder"}]),
            chk("no_overlap", 1, selector={"type": ["shape", "sticky"]})])],
     [[call("create_frame", title="Clients", x=100, y=100, w=500, h=700),
       call("create_frame", title="Services", x=700, y=100, w=700, h=700),
       call("create_frame", title="Data", x=1500, y=100, w=500, h=700)]
      + [call("create_shape", as_=i, kind=k, x=x, y=y, w=w, h=110 if k == "cylinder" else 90, text=t)
         for i, t, x, y, k, w in ARCH_NODES]
      + [call("create_connector", source_id="$" + _arch_ids[a], target_id="$" + _arch_ids[b]) for a, b in ARCH_EDGES]],
     skills=["architecture diagrams", "grouping", "notation"])


def _box(x0, y0, x1, y1, j=6):
    return [[x0 + j, y0], [x1 - j, y0 + j], [x1, y1 - j], [x0 + j, y1], [x0, y0 + j * 2], [x0 + j * 2, y0 - 2]]


def _arrow(x0, y0, x1, y1):
    import math
    ang = math.atan2(y1 - y0, x1 - x0)
    a1 = [x1 - 18 * math.cos(ang - 0.5), y1 - 18 * math.sin(ang - 0.5)]
    a2 = [x1 - 18 * math.cos(ang + 0.5), y1 - 18 * math.sin(ang + 0.5)]
    return [[x0, y0], [(x0 + x1) / 2, (y0 + y1) / 2 + 4], [x1, y1], a1, [x1, y1], a2]


SKETCH = [("Sensor", 180, 380, 360, 460), ("Edge Hub", 600, 380, 780, 460), ("Cloud Ingest", 1020, 380, 1220, 460),
          ("Dashboard", 1440, 240, 1620, 320), ("Alerts", 1440, 540, 1620, 620)]
SKETCH_ARROWS = [(365, 420, 595, 421), (785, 420, 1015, 421), (1225, 405, 1435, 285), (1225, 440, 1435, 578)]
task("dg_sketch_to_diagram", "diagramming", "Clean up a hand-drawn sketch into a diagram", "hard", DESK,
     [turn("I sketched our IoT pipeline by hand: the strokes and labels on the board. Turn it into a clean "
           "diagram: a proper shape for each labeled box, real connectors that follow my arrows in the same "
           "direction, then remove my rough strokes and the loose labels you've replaced. Keep roughly the same layout.",
           [chk("graph", 5, "topology matches the sketch", nodes=["Sensor", "Edge Hub", "Cloud Ingest", "Dashboard", "Alerts"],
                edges=[["Sensor", "Edge Hub"], ["Edge Hub", "Cloud Ingest"], ["Cloud Ingest", "Dashboard"],
                       ["Cloud Ingest", "Alerts"]]),
            chk("count", 1, "shapes created", selector={"type": "shape"}, min=5, max=6),
            chk("count", 1.5, "rough strokes removed", selector={"type": "stroke"}, max=0),
            chk("count", 1, "loose labels removed", selector={"type": "text", "author": "human"}, max=0),
            chk("relation", 1.5, "layout preserved", items=[
                {"a": "Sensor", "rel": "left_of", "b": "Edge Hub"}, {"a": "Edge Hub", "rel": "left_of", "b": "Cloud Ingest"},
                {"a": "Cloud Ingest", "rel": "left_of", "b": "Dashboard"}, {"a": "Dashboard", "rel": "above", "b": "Alerts"}]),
            chk("no_overlap", 1, selector={"type": ["shape", "text", "sticky"]})])],
     [[call("create_shape", as_=f"n{i}", kind="rect", x=x0, y=y0, w=x1 - x0, h=y1 - y0, text=t)
       for i, (t, x0, y0, x1, y1) in enumerate(SKETCH)]
      + [call("create_connector", source_id="$n0", target_id="$n1"), call("create_connector", source_id="$n1", target_id="$n2"),
         call("create_connector", source_id="$n2", target_id="$n3"), call("create_connector", source_id="$n2", target_id="$n4"),
         call("delete_elements", ids=find_all(type="stroke")),
         call("delete_elements", ids=find_all(type="text", author="human"))]],
     initial=[text(t, x0 + 20, y0 + 20, author="human:maya", w=x1 - x0 - 40) for t, x0, y0, x1, y1 in SKETCH]
     + [dict(type="stroke", points=_box(x0, y0, x1, y1), author="human:maya") for _, x0, y0, x1, y1 in SKETCH]
     + [dict(type="stroke", points=_arrow(*a), author="human:maya") for a in SKETCH_ARROWS],
     participants={"maya": PEOPLE["maya"]},
     skills=["sketch interpretation", "spatial reasoning", "cleanup"])

SM = {"Created": (100, 300), "Paid": (400, 300), "Shipped": (700, 300), "Delivered": (1000, 300), "Cancelled": (400, 560)}
SM_EDGES1 = [["Created", "Paid"], ["Paid", "Shipped"], ["Shipped", "Delivered"], ["Created", "Cancelled"], ["Paid", "Cancelled"]]
SM_EDGES2 = SM_EDGES1 + [["Delivered", "Refunded"], ["Cancelled", "Refunded"]]
task("dg_state_machine_iterative", "diagramming", "Evolve a state machine with a collaborator", "medium", DESK,
     [turn("Draw a state machine for an order: Created → Paid → Shipped → Delivered. Also Created → Cancelled "
           "and Paid → Cancelled.",
           [chk("graph", 3, "initial state machine", nodes=list(SM), edges=SM_EDGES1)]),
      turn("I added 'Refunded' as a sticky. Wire it in: both Delivered and Cancelled can move to Refunded. And swap "
           "my sticky for a proper state shape like the others.",
           [chk("graph", 3, "Refunded wired in", nodes=list(SM) + ["Refunded"], edges=SM_EDGES2),
            chk("property", 1, "Refunded is a shape", items=[{"text": "Refunded", "field": "type", "value": "shape"}]),
            chk("count", 1, "sticky replaced, not duplicated", selector={"type": "sticky", "text": "Refunded"}, max=0)],
           events=[{"op": "create", "actor": "human:maya", "near": "Delivered", "offset": [0, 260],
                    "element": {"type": "sticky", "text": "Refunded", "color": "pink"}}],
           speaker="human:maya"),
      turn("Rename 'Shipped' to 'In Transit'. Then color Refunded green and Cancelled red.", speaker="human:maya")],
     [[call("create_shape", as_=k, kind="rounded_rect", x=x, y=y, text=k) for k, (x, y) in SM.items()]
      + [call("create_connector", source_id="$" + a, target_id="$" + b) for a, b in SM_EDGES1],
      [call("delete_elements", ids=[find("Refunded", type="sticky")]),
       call("create_shape", as_="Refunded", kind="rounded_rect", x=1000, y=560, text="Refunded"),
       call("create_connector", source_id="$Delivered", target_id="$Refunded"),
       call("create_connector", source_id="$Cancelled", target_id="$Refunded")],
      [call("update_element", id="$Shipped", text="In Transit"),
       call("update_element", id="$Refunded", color="green"),
       call("update_element", id="$Cancelled", color="red")]],
     participants={"maya": PEOPLE["maya"]},
     final=[chk("graph", 3, "final state machine", nodes=["Created", "Paid", "In Transit", "Delivered", "Cancelled", "Refunded"],
                edges=[[("In Transit" if n == "Shipped" else n) for n in e] for e in SM_EDGES2]),
            chk("texts_absent", 1, "old name gone", items=["Shipped"]),
            chk("property", 2, "colors applied", items=[{"text": "Refunded", "field": "color", "value": "green"},
                                                         {"text": "Cancelled", "field": "color", "value": "red"}]),
            chk("no_overlap", 1, selector={"type": ["shape", "sticky"]})],
     skills=["state machines", "iteration", "respecting collaborator input"])

ORG = [("dana", "Dana Reyes, CEO", 700, 100, None), ("omar", "Omar Haddad, CTO", 250, 300, "dana"),
       ("lin", "Lin Park, CFO", 700, 300, "dana"), ("tom", "Tom Ruiz, VP Sales", 1150, 300, "dana"),
       ("aisha", "Aisha Bello, Eng Manager", 100, 500, "omar"), ("ken", "Ken Ito, Security Lead", 400, 500, "omar"),
       ("rosa", "Rosa Diaz, Account Exec", 1150, 500, "tom")]
_names = {k: t.split(",")[0] for k, t, *_ in ORG}
task("dg_org_chart", "diagramming", "Org chart with tree layout", "easy", DESK,
     [turn("Make an org chart. CEO Dana Reyes. Reporting to Dana: CTO Omar Haddad, CFO Lin Park, VP Sales Tom Ruiz. "
           "Reporting to Omar: Eng Manager Aisha Bello and Security Lead Ken Ito. Reporting to Tom: Account Exec Rosa "
           "Diaz. Use a tree layout with managers above their reports and connectors from each manager to each report.",
           [chk("graph", 4, "reporting lines", nodes=list(_names.values()),
                edges=[[_names[p], _names[k]] for k, _, _, _, p in ORG if p]),
            chk("relation", 2, "managers above reports", items=[
                {"a": _names[p], "rel": "above", "b": _names[k]} for k, _, _, _, p in ORG if p]),
            chk("aligned", 1, "peers share a row", items=["Omar Haddad", "Lin Park", "Tom Ruiz"], axis="y"),
            chk("aligned", 1, "third level shares a row", items=["Aisha Bello", "Ken Ito", "Rosa Diaz"], axis="y"),
            chk("texts_present", 1, "titles included", items=["CEO", "CTO", "CFO", "VP Sales", "Eng Manager|Engineering Manager",
                                                              "Security Lead", "Account Exec|Account Executive"]),
            chk("no_overlap", 1, selector={"type": ["shape", "sticky", "text"]})])],
     [[call("create_shape", as_=k, kind="rounded_rect", x=x, y=y, w=240, h=90, text=t) for k, t, x, y, _ in ORG]
      + [call("create_connector", source_id="$" + p, target_id="$" + k) for k, _, _, _, p in ORG if p]],
     skills=["hierarchies", "tree layout"])

# ================================================================= BRAINSTORMING
IDEAS = ["Late-night gaming tournaments in the library", "Teen-run podcast studio with free recording gear",
         "Makerspace with 3D printers and laser cutters", "Manga and graphic novel club with artist visits",
         "Homework help from college student volunteers", "Anime watch parties with snacks",
         "Library card unlocks free streaming and ebooks", "Teen advisory board that picks new books",
         "Coding bootcamp for building mobile games", "Quiet study pods bookable by phone",
         "Open mic poetry and music nights", "Job skills workshops: resumes, interviews, first jobs",
         "Book-to-movie screenings with discussion", "Scavenger hunts using augmented reality",
         "Free phone charging lounge", "Volunteer hours credit for reading to younger kids"]
task("bs_divergent_ideas", "brainstorming", "Divergent idea generation", "easy", DESK,
     [turn("Brainstorm with me: ways a public library could attract more teenagers. Put at least 15 ideas as "
           "stickies inside a frame called 'Library x Teens', one idea per sticky. Make them varied, not "
           "rephrasings of the same idea.",
           [chk("frames", 1, titles=["Library x Teens"]),
            chk("count", 2, "at least 15 ideas in the frame", selector={"type": "sticky", "frame": "Library x Teens"}, min=15),
            chk("distinct", 2, "ideas are distinct", selector={"type": "sticky"}, min=15),
            chk("max_words", 1, "sticky-sized ideas", selector={"type": "sticky"}, max=15),
            chk("no_overlap", 1),
            chk("rubric", 3, "idea quality (judge)", question="Are the ideas varied rather than rephrasings, specific "
                "enough to act on, and plausible for a public library to try?")])],
     [[call("create_frame", title="Library x Teens", x=100, y=100, w=1100, h=920)]
      + [call("create_sticky", text=t, x=130 + 210 * (i % 5), y=170 + 210 * (i // 5)) for i, t in enumerate(IDEAS)]],
     skills=["ideation", "divergence"])

QUOTES = {
    "Price & value": ["Too expensive for a weeknight dinner", "I'd order more with a cheaper plan",
                      "The delivery fee feels like a scam", "The grocery store is half the cost"],
    "Packaging waste": ["So much plastic in every box", "I feel guilty about all the ice packs",
                        "Wish the packaging was compostable"],
    "Time & effort": ["Recipes take way longer than advertised", "Too much chopping after work",
                      "I want 15-minute options", "Cleanup is a nightmare"],
    "Scheduling flexibility": ["I always forget to skip a week", "Can't change my delivery day easily",
                               "Pausing my subscription was painful", "Skipping requires too many clicks"],
    "Menu variety": ["The menu repeats too often", "Want more vegetarian variety", "Same five cuisines every week"],
}
_mixed = [q for i in range(4) for qs in QUOTES.values() for q in qs[i:i + 1]]
task("bs_affinity_mapping", "brainstorming", "Affinity map of user-research quotes", "hard", DESK,
     [turn("Here are 18 quotes from our meal-kit user interviews. Do an affinity map: group them into themes, with "
           "a labeled frame per theme. Don't reword the quotes.",
           [chk("clusters", 5, "grouping matches the underlying themes", groups=list(QUOTES.values()), method="frame"),
            chk("preserve_human", 2, "quotes kept verbatim"),
            chk("count", 1, "a sensible number of themes", selector={"type": "frame", "author": "agent"}, min=4, max=7),
            chk("no_overlap", 1),
            chk("rubric", 1, "theme labels (judge)", question="Do the theme frame titles name the underlying user "
                "need clearly and concisely?")])],
     [[call("create_frame", title=th, x=100 + 440 * i, y=900, w=420, h=460) for i, th in enumerate(QUOTES)]
      + [call("move_elements", moves=[{"id": find(q), "x": 120 + 440 * i + 200 * (j % 2), "y": 960 + 190 * (j // 2)}
                                      for i, qs in enumerate(QUOTES.values()) for j, q in enumerate(qs)])]],
     initial=[frame("Interview quotes", 100, 100, 1250, 720, author="human:maya")]
     + [sticky(q, 130 + 200 * (i % 6), 170 + 200 * (i // 6), author="human:maya") for i, q in enumerate(_mixed)],
     participants={"maya": PEOPLE["maya"]},
     skills=["synthesis", "clustering", "labeling"])

SEEDS = [("Cooking class together", "maya", 200, 200), ("Volunteer day at a food bank", "sam", 1200, 200),
         ("Escape room challenge", "lee", 200, 650), ("Hackathon on internal tools", "priya", 1200, 650)]
BUILDS = [["Cook dishes from each teammate's home country", "End with a shared dinner we cooked"],
          ["Let the team vote on which charity", "Company matches donations per volunteer hour"],
          ["Mix people from different teams in each squad", "Design our own puzzle room next year"],
          ["Demo day with prizes voted by everyone", "Pair people across departments"]]
task("bs_yes_and", "brainstorming", "Build on teammates' ideas ('yes, and')", "medium", DESK,
     [turn("Build on each of these ideas: for every sticky the team added, add at least two 'yes, and...' "
           "stickies that extend it. Place them near the idea they build on, connect each one to its source, and use "
           "a different color from the originals.",
           [chk("each_connected", 4, "every idea has 2+ nearby builds connected",
                **{"from": {"type": "sticky", "author": "human"}, "to": {"type": "sticky", "author": "agent"}},
                min=2, near=450),
            chk("property", 1, "builds use a different color",
                items=[{"selector": {"type": "sticky", "author": "agent"}, "field": "color", "value": "yellow", "op": "ne"}]),
            chk("preserve_human", 1, "original ideas untouched"),
            chk("max_words", 0.5, selector={"type": "sticky", "author": "agent"}, max=15),
            chk("no_overlap", 1),
            chk("rubric", 1, "builds extend their source (judge)", question="Does each new sticky genuinely extend "
                "the specific idea it is connected to, rather than being generic or unrelated?")])],
     [[step for i, (_, _, x, y) in enumerate(SEEDS) for j, b in enumerate(BUILDS[i]) for step in (
         call("create_sticky", as_=f"b{i}{j}", text=b, x=x + 220, y=y - 80 + 200 * j, color="blue"),
         call("create_connector", source_id=find(SEEDS[i][0], type="sticky"), target_id=f"$b{i}{j}"))]],
     initial=[frame("Team offsite ideas", 100, 100, 1600, 1000)]
     + [sticky(t, x, y, author=f"human:{a}") for t, a, x, y in SEEDS],
     participants={k: PEOPLE[k] for k in ("maya", "sam", "lee", "priya")},
     skills=["generative building", "linking", "respecting others' work"])

VOTES = [("Referral program", 7), ("Free tier", 2), ("Annual discount", 5), ("Webinar series", 1),
         ("Partner integrations", 6), ("Student pricing", 3), ("Community forum", 4), ("Podcast ads", 0)]
task("bs_dot_vote_converge", "brainstorming", "Converge after dot voting, then handle late votes", "medium", DESK,
     [turn("Dot voting is done. Move the top 3 ideas by votes into 'Next Steps', ordered left to right by votes, "
           "and tell us in chat which three made it and their vote counts.",
           [chk("in_frame", 3, "top 3 moved", items=[{"text": t, "frame": "Next Steps"} for t in
                                                      ("Referral program", "Partner integrations", "Annual discount")]),
            chk("order", 1, "ordered by votes", axis="x", items=["Referral program", "Partner integrations", "Annual discount"]),
            chk("said", 1, "reported results", items=["Referral 7", "Partner integrations 6", "Annual discount 5"]),
            chk("preserve_human", 1, "ideas not reworded")]),
      turn("Sam just cast his late votes. Update Next Steps if the top three changed, keep them ordered by votes "
           "left to right, and tell us what changed.",
           [chk("in_frame", 3, "top 3 updated", items=[
               {"text": "Community forum", "frame": "Next Steps"}, {"text": "Referral program", "frame": "Next Steps"},
               {"text": "Partner integrations", "frame": "Next Steps"}, {"text": "Annual discount", "frame": "Ideas"}]),
            chk("order", 1, "re-ordered by votes", axis="x", items=["Community forum", "Referral program", "Partner integrations"]),
            chk("said", 1, "explained the change", items=["Community forum"]),
            chk("preserve_human", 1, "ideas not reworded")],
           events=[{"op": "vote", "actor": "human:sam", "target": "Community forum", "count": 4}])],
     [[call("move_elements", moves=[{"id": find("Referral program"), "x": 1130, "y": 170},
                                    {"id": find("Partner integrations"), "x": 1330, "y": 170},
                                    {"id": find("Annual discount"), "x": 1530, "y": 170}]),
       call("say", message="Top 3: Referral program (7 votes), Partner integrations (6), Annual discount (5).")],
      [call("move_elements", moves=[{"id": find("Annual discount"), "x": 550, "y": 170},
                                    {"id": find("Community forum"), "x": 1130, "y": 170},
                                    {"id": find("Referral program"), "x": 1330, "y": 170},
                                    {"id": find("Partner integrations"), "x": 1530, "y": 170}]),
       call("say", message="Community forum jumped to 8 votes and is now first. Annual discount (5) dropped out and "
                           "went back to Ideas. New order: Community forum 8, Referral program 7, Partner integrations 6.")]],
     initial=[frame("Ideas", 100, 100, 900, 560), frame("Next Steps", 1100, 100, 760, 300)]
     + [sticky(t, 130 + 210 * (i % 4), 170 + 210 * (i // 4), votes=v) for i, (t, v) in enumerate(VOTES)],
     participants={"sam": PEOPLE["sam"]},
     skills=["convergence", "reading state", "reacting to change"])

# ====================================================================== PLANNING
RETRO_GOOD = [("Shipped search on time", "maya"), ("Great pairing sessions", "sam")]
RETRO_BAD = [("Deploys kept failing", "sam"), ("Too many meetings", "priya"), ("CI pipeline is flaky", "lee"),
             ("Standups ran way too long", "lee"), ("Broken builds slowed us down", "maya")]
task("pl_retro_iterative", "planning", "Run a sprint retro across three rounds", "hard", DESK,
     [turn("Set up a sprint retro board: three columns as frames, 'Went well', 'Didn't go well', and 'Try next', "
           "left to right, with a title 'Sprint 42 Retro' above them.",
           [chk("frames", 2, titles=["Went well", "Didn't go well", "Try next"]),
            chk("texts_present", 1, "title", items=["Sprint 42 Retro"]),
            chk("order", 1, "columns left to right", axis="x", where={"type": "frame"},
                items=["Went well", "Didn't go well", "Try next"]),
            chk("relation", 0.5, "title above columns", items=[{"a": "Sprint 42 Retro", "rel": "above", "b": "Went well"}])]),
      turn("Everyone's added their notes. In 'Didn't go well', cluster notes about the same underlying problem side "
           "by side under a short header for each problem, with clear space between clusters. Don't delete or "
           "reword anyone's notes.",
           [chk("clusters", 4, "notes grouped by underlying problem", method="spatial", gap=60,
                pool={"type": "sticky", "frame": "Didn't go well"},
                groups=[["Deploys kept failing", "CI pipeline is flaky", "Broken builds slowed us down"],
                        ["Too many meetings", "Standups ran way too long"]]),
            chk("preserve_human", 2, "nobody's notes deleted or reworded"),
            chk("count", 1, "a header per cluster", selector={"author": "agent", "frame": "Didn't go well"}, min=2, max=4),
            chk("no_overlap", 1, selector={"frame": "Didn't go well"})],
           events=[{"op": "create", "actor": f"human:{a}", "into_frame": "Went well", "element": {"type": "sticky", "text": t}}
                   for t, a in RETRO_GOOD]
           + [{"op": "create", "actor": f"human:{a}", "into_frame": "Didn't go well",
               "element": {"type": "sticky", "text": t, "color": "pink"}} for t, a in RETRO_BAD]),
      turn("For each problem cluster, add one concrete action item to 'Try next' and connect it to that problem's header.",
           [chk("each_connected", 3, "each action links to a problem header",
                **{"from": {"author": "agent", "frame": "Try next"}, "to": {"author": "agent", "frame": "Didn't go well"}}),
            chk("count", 1, "one action per cluster", selector={"author": "agent", "frame": "Try next"}, min=2, max=3),
            chk("rubric", 1, "actions are concrete (judge)", question="Are the action items in 'Try next' concrete, "
                "owned or time-bound, and clearly aimed at the problems they connect to?")])],
     [[call("create_text", text="Sprint 42 Retro", x=100, y=40, font_size=40),
       call("create_frame", title="Went well", x=100, y=150, w=600, h=900),
       call("create_frame", title="Didn't go well", x=750, y=150, w=700, h=900),
       call("create_frame", title="Try next", x=1500, y=150, w=600, h=900)],
      [call("create_text", as_="h1", text="Build & deploy reliability", x=780, y=220, w=500),
       call("create_text", as_="h2", text="Meeting overload", x=780, y=520, w=400),
       call("move_elements", moves=[{"id": find("Deploys kept failing"), "x": 780, "y": 270},
                                    {"id": find("CI pipeline is flaky"), "x": 960, "y": 270},
                                    {"id": find("Broken builds slowed us down"), "x": 1140, "y": 270},
                                    {"id": find("Too many meetings"), "x": 780, "y": 570},
                                    {"id": find("Standups ran way too long"), "x": 960, "y": 570}])],
      [call("create_sticky", as_="a1", text="Sam: quarantine flaky tests + add CI retries by next sprint", x=1530, y=220, color="green"),
       call("create_sticky", as_="a2", text="Cap standups at 15 min; no-meeting Wednesdays", x=1530, y=520, color="green"),
       call("create_connector", source_id="$h1", target_id="$a1"),
       call("create_connector", source_id="$h2", target_id="$a2")]],
     participants={k: PEOPLE[k] for k in ("maya", "sam", "lee", "priya")},
     skills=["facilitation templates", "clustering others' notes", "action planning"])

MATRIX = [("Dark mode", "lo", "lo"), ("SSO login", "hi", "hi"), ("Fix checkout bug", "hi", "lo"),
          ("Rewrite in Rust", "lo", "hi"), ("Bulk CSV import", "hi", "lo"), ("Animated mascot", "lo", "hi"),
          ("Offline mode", "hi", "hi"), ("Keyboard shortcuts", "lo", "lo")]
QUAD = {("hi", "lo"): ("Quick Wins", 100, 100), ("hi", "hi"): ("Big Bets", 850, 100),
        ("lo", "lo"): ("Fill-ins", 100, 650), ("lo", "hi"): ("Money Pit", 850, 650)}
_slot = {}
task("pl_impact_effort_matrix", "planning", "Impact/effort 2x2 prioritization", "medium", DESK,
     [turn("Set up an impact/effort 2x2 and place these features. Impact goes from low at the bottom to high at the "
           "top; effort goes from low on the left to high on the right. Label the quadrants 'Quick Wins' (high impact, "
           "low effort), 'Big Bets' (high impact, high effort), 'Fill-ins' (low impact, low effort), and 'Money Pit' "
           "(low impact, high effort). Features: Dark mode (low impact, low effort), SSO login (high, high), Fix "
           "checkout bug (high impact, low effort), Rewrite in Rust (low impact, high effort), Bulk CSV import (high "
           "impact, low effort), Animated mascot (low impact, high effort), Offline mode (high, high), Keyboard "
           "shortcuts (low, low).",
           [chk("quadrants", 4, "relative placement is consistent", items=[{"text": t, "v": v, "h": h} for t, v, h in MATRIX]),
            chk("nearest_label", 3, "each feature sits in its labeled quadrant",
                labels=["Quick Wins", "Big Bets", "Fill-ins", "Money Pit"],
                items=[{"text": t, "label": QUAD[(v, h)][0]} for t, v, h in MATRIX]),
            chk("texts_present", 1, "quadrant labels", where={"type": ["frame", "text", "shape", "sticky"]},
                items=["Quick Wins", "Big Bets", "Fill-ins|Fill ins", "Money Pit"]),
            chk("no_overlap", 1)])],
     [[call("create_frame", title=name, x=x, y=y, w=700, h=500) for name, x, y in QUAD.values()]
      + [call("create_text", text="Impact ↑", x=20, y=40, w=160), call("create_text", text="Effort →", x=1400, y=1170, w=160)]
      + [call("create_sticky", text=t, x=QUAD[(v, h)][1] + 50 + 200 * _slot.setdefault((v, h), [0, 1]).pop(0),
              y=QUAD[(v, h)][2] + 100) for t, v, h in MATRIX]],
     skills=["prioritization frameworks", "spatial semantics"])

CARDS = ["Design login page", "Set up CI", "Write API docs", "User interviews", "Fix memory leak"]
task("pl_kanban_updates", "planning", "Kanban board kept in sync with status updates", "medium", DESK,
     [turn("Make a kanban board with columns To Do, In Progress, and Done. Cards: 'Design login page', 'Set up CI', "
           "'Write API docs', 'User interviews', 'Fix memory leak'. They all start in To Do.",
           [chk("frames", 1, titles=["To Do", "In Progress", "Done"]),
            chk("order", 0.5, "columns left to right", axis="x", where={"type": "frame"}, items=["To Do", "In Progress", "Done"]),
            chk("in_frame", 2, "cards start in To Do", items=[{"text": c, "frame": "To Do"} for c in CARDS])]),
      turn("Update the board from Sam's update.",
           [chk("in_frame", 3, "statuses updated", items=[
               {"text": "Set up CI", "frame": "In Progress"}, {"text": "Fix memory leak", "frame": "In Progress"},
               {"text": "User interviews", "frame": "Done"}, {"text": "Design login page", "frame": "To Do"},
               {"text": "Write API docs", "frame": "To Do"}])],
           events=[{"op": "say", "actor": "human:sam", "text": "Quick update: I started on CI and the memory leak. "
                    "Oh, and the user interviews are finished, Maya ran them."}]),
      turn("Set up CI is done now. Also tidy the columns so no cards overlap.",
           events=[{"op": "move", "actor": "human:lee", "target": "Design login page", "near": "Fix memory leak",
                    "offset": [30, 40]}])],
     [[call("create_frame", title="To Do", x=100, y=100, w=400, h=1100),
       call("create_frame", title="In Progress", x=550, y=100, w=400, h=1100),
       call("create_frame", title="Done", x=1000, y=100, w=400, h=1100)]
      + [call("create_sticky", text=c, x=130, y=170 + 120 * i, w=340, h=100) for i, c in enumerate(CARDS)],
      [call("move_elements", moves=[{"id": find("Set up CI"), "x": 580, "y": 170},
                                    {"id": find("Fix memory leak"), "x": 580, "y": 290},
                                    {"id": find("User interviews"), "x": 1030, "y": 170}])],
      [call("move_elements", moves=[{"id": find("Set up CI"), "x": 1030, "y": 290},
                                    {"id": find("Design login page"), "x": 580, "y": 410}])]],
     participants={k: PEOPLE[k] for k in ("maya", "sam", "lee")},
     final=[chk("in_frame", 4, "final statuses (Lee's move respected)", items=[
                {"text": "Design login page", "frame": "In Progress"}, {"text": "Fix memory leak", "frame": "In Progress"},
                {"text": "Set up CI", "frame": "Done"}, {"text": "User interviews", "frame": "Done"},
                {"text": "Write API docs", "frame": "To Do"}]),
            chk("count", 1, "no duplicate cards", selector={"type": ["sticky", "shape"]}, min=5, max=5, strict=True),
            chk("no_overlap", 2)],
     skills=["state tracking", "inferring intent from speech", "respecting others' moves"])

# ================================================================ COLLABORATION
MAYA_SEC = ["Persona: busy parent", "Journey: signup", "Journey: first order", "Pain: slow checkout", "Pain: unclear pricing"]
PARKING = [("Budget approval?", "sam", 1050, 200), ("Localization later", "lee", 1120, 240),
           ("Revisit dark patterns", "priya", 1300, 180), ("Who owns analytics?", "sam", 1330, 260),
           ("Legal: data retention", "lee", 1500, 400), ("Partner API access", "priya", 1080, 500),
           ("Holiday code freeze", "facilitator", 1150, 540)]
task("co_protected_region", "collaboration", "Tidy one area while a colleague presents from another", "medium", DESK,
     [turn("Please tidy up the Parking lot into a neat grid with no overlaps. Maya is still presenting from her "
           "section, so don't move or change anything in it.",
           [chk("preserve_human", 3, "Maya's section untouched", selector={"frame": "Maya's section"}, positions=True, tol=2),
            chk("no_overlap", 2, "parking lot has no overlaps", selector={"frame": "Parking lot"}),
            chk("grid_aligned", 1, "parking lot is a grid", selector={"frame": "Parking lot"}),
            chk("in_frame", 2, "all parking-lot items (incl. Sam's new one) stay in it", guard=True,
                items=[{"text": t, "frame": "Parking lot"} for t, *_ in PARKING] + [{"text": "Hire a contractor", "frame": "Parking lot"}]),
            chk("preserve_human", 1, "nobody's text changed")],
           events=[{"op": "create", "actor": "human:sam", "at_call": 3, "into_frame": "Parking lot", "placement": "center",
                    "element": {"type": "sticky", "text": "Hire a contractor?"}}])],
     [[call("arrange", ids=find_all(frame="Parking lot", type="sticky"), layout="grid", x=1040, y=170, columns=4, gap=30),
       call("arrange", ids=find_all(frame="Parking lot", type="sticky"), layout="grid", x=1040, y=170, columns=4, gap=30)]],
     initial=[frame("Maya's section", 100, 100, 800, 600, author="human:maya"), frame("Parking lot", 1000, 100, 900, 800)]
     + [sticky(t, 150 + 200 * (i % 3), 200 + 200 * (i // 3), author="human:maya", color="pink") for i, t in enumerate(MAYA_SEC)]
     + [sticky(t, x, y, author=f"human:{a}") for t, a, x, y in PARKING],
     participants={k: PEOPLE[k] for k in ("maya", "sam", "lee", "priya")},
     skills=["scoped edits", "concurrent editing", "tidying"])

GRID9 = [("Weekly demo day", "yellow"), ("Better docs search", "blue"), ("Kill unused dashboards", "pink"),
         ("Async standups", "pink"), ("Rotate on-call fairly", "yellow"), ("Mentorship pairs", "blue"),
         ("Team lunch fund", "blue"), ("Quarterly hack week", "pink"), ("Shorter sprints", "yellow")]
_rows = {"yellow": 0, "blue": 1, "pink": 2}
_cols = {"yellow": 0, "blue": 0, "pink": 0}
_sorted_moves = []
for t, c in GRID9:
    _sorted_moves.append({"id": find(t), "x": 130 + 220 * _cols[c], "y": 170 + 220 * _rows[c]})
    _cols[c] += 1
task("co_undo_restore", "collaboration", "Reorganize, then restore on request", "easy", DESK,
     [turn("Sort these into rows by color: all the yellow ones in the top row, blue in the middle row, pink in the bottom row.",
           [chk("aligned", 1, "yellow row", selector={"type": "sticky", "color": "yellow"}, axis="y"),
            chk("aligned", 1, "blue row", selector={"type": "sticky", "color": "blue"}, axis="y"),
            chk("aligned", 1, "pink row", selector={"type": "sticky", "color": "pink"}, axis="y"),
            chk("relation", 1, "row order", items=[{"a": "Weekly demo day", "rel": "above", "b": "Better docs search"},
                                                   {"a": "Better docs search", "rel": "above", "b": "Kill unused dashboards"}]),
            chk("no_overlap", 1)]),
      turn("Hmm, I liked the original arrangement better. Put everything back exactly where it was before you sorted.",
           [chk("matches_snapshot", 4, "original positions restored", snapshot="initial",
                selector={"type": "sticky"}, tol=3,
                requires_change=["initial", "turn1_end"])])],
     [[call("move_elements", moves=_sorted_moves)], [call("undo")]],
     initial=[frame("Ideas", 100, 100, 760, 760)]
     + [sticky(t, 130 + 220 * (i % 3), 170 + 220 * (i // 3), color=c) for i, (t, c) in enumerate(GRID9)],
     skills=["undo", "memory of prior state"])

task("co_conflicting_requests", "collaboration", "Mediate conflicting requests from two people", "hard", DESK,
     [turn("You heard them both. Handle it the way a good facilitator would.",
           [chk("texts_present", 2, "both proposals on the board", items=["Ship it", "collaborative workspace engineering teams"]),
            chk("texts_present", 1, "proposals attributed", items=["Maya", "Sam"]),
            chk("preserve_human", 1, "current headline not overwritten"),
            chk("aligned", 1, "options shown side by side", items=["Ship it", "collaborative workspace"], axis="y", tol=40),
            chk("said", 1, "invites the group to decide", any=True,
                items=["vote", "decide", "which one", "prefer", "test both", "pick"]),
            chk("rubric", 1, "facilitation quality (judge)", question="Did the AI surface both proposals fairly and "
                "hand the decision back to the group (vote, test, or discuss) instead of picking a winner on its own?")],
           events=[{"op": "say", "actor": "human:maya", "text": "Make the headline punchier. Something like 'Ship it.'"},
                   {"op": "say", "actor": "human:sam", "text": "No, it should stay descriptive, like 'The collaborative "
                    "workspace for engineering teams'."}])],
     [[call("create_sticky", text="Option A (Maya): Ship it.", x=150, y=400, w=300, h=120, color="pink"),
       call("create_sticky", text="Option B (Sam): The collaborative workspace for engineering teams", x=500, y=400,
            w=300, h=120, color="blue"),
       call("say", message="I've put Maya's and Sam's options side by side under the current headline. Want to dot-vote, "
                           "or test both on the landing page and decide from the data?")]],
     initial=[frame("Homepage headline", 100, 100, 1000, 600), sticky("Build faster together", 150, 200, w=300, h=120)],
     participants={k: PEOPLE[k] for k in ("maya", "sam")},
     skills=["mediation", "neutrality", "making disagreement visible"])

# =================================================================== XR / SPATIAL
task("xr_deixis_pointing", "xr_spatial", "Resolve 'here', 'this' and 'that' from pointing", "medium", XR,
     [turn("Put a note right here that says 'Ship it Friday'.",
           [chk("near_point", 3, "note placed where Maya pointed", items=[{"text": "Ship it Friday", "point": [620, 540], "radius": 60}]),
            chk("in_frame", 1, items=[{"text": "Ship it Friday", "frame": "Launch checklist"}])],
           events=[{"op": "point", "actor": "human:maya", "at": [620, 540]}], speaker="human:maya"),
      turn("This one blocks that one. Connect them so it's obvious.",
           [chk("graph", 3, "blocker points at the blocked item", nodes=["Legal review pending", "Press release"],
                edges=[["Legal review pending", "Press release"]]),
            chk("count", 1, "no spurious connectors", selector={"type": "connector"}, max=1)],
           events=[{"op": "point", "actor": "human:maya", "target": "Legal review pending", "jitter": [15, -10]},
                   {"op": "point", "actor": "human:maya", "target": "Press release", "jitter": [-20, 5]}],
           speaker="human:maya"),
      turn("Make this one red and move it over to the checklist, right next to QA.",
           [chk("property", 1.5, "recolored the pointed-at item", items=[{"text": "Server capacity", "field": "color", "value": "red"}]),
            chk("relation", 1.5, "placed next to QA", items=[{"a": "Server capacity", "rel": "near", "b": "QA sign-off", "dist": 260}]),
            chk("in_frame", 1, items=[{"text": "Server capacity", "frame": "Launch checklist"}]),
            chk("no_overlap", 1)],
           events=[{"op": "point", "actor": "human:maya", "target": "Server capacity", "jitter": [-12, 20]}],
           speaker="human:maya")],
     [[call("create_sticky", text="Ship it Friday", x=540, y=460, color="green")],
      [call("create_connector", source_id={"$at": [1295, 520]}, target_id={"$at": [260, 535]}, label="blocks")],
      [call("update_element", id={"$at": [1268, 300]}, color="red"),
       call("move_elements", moves=[{"id": find("Server capacity"), "x": 390, "y": 200}])]],
     initial=[frame("Launch checklist", 100, 100, 900, 700), sticky("QA sign-off", 200, 200),
              sticky("Press release", 200, 450), sticky("Update docs", 650, 200),
              frame("Risks", 1100, 100, 700, 700), sticky("Server capacity", 1200, 200, color="orange"),
              sticky("Legal review pending", 1200, 450, color="orange")],
     participants={"maya": PEOPLE["maya"]},
     skills=["deixis", "multimodal grounding"])

REACH = {"maya": {"name": "Maya", "color": "pink", "reach": {"x": 0, "y": 300, "w": 1300, "h": 1200},
                  "note": "Standing at the left of the wall."},
         "sam": {"name": "Sam", "color": "blue", "reach": {"x": 1300, "y": 300, "w": 1300, "h": 1200},
                 "note": "Standing at the center of the wall."},
         "lee": {"name": "Lee", "color": "green", "reach": {"x": 2600, "y": 300, "w": 1300, "h": 1200},
                 "note": "Standing at the right of the wall."}}
ACTIONS = [("Maya: book the venue", "maya"), ("Sam: send invites", "sam"), ("Lee: order catering", "lee"),
           ("Maya: draft the agenda", "maya"), ("Sam: arrange AV equipment", "sam"), ("Lee: collect dietary needs", "lee")]
_reach_x = {"maya": 400, "sam": 1700, "lee": 3000}
_reach_n = {"maya": 0, "sam": 0, "lee": 0}
_reach_moves = []
for t, who in ACTIONS:
    _reach_moves.append({"id": find(t), "x": _reach_x[who] + 200 * _reach_n[who], "y": 700})
    _reach_n[who] += 1
task("xr_reach_zones", "xr_spatial", "Hand out items within each person's reach", "medium", XR,
     [turn("Everyone's at the wall now. Hand each person their own action items: move each item to within that "
           "person's arm's reach, and color each person's items with their participant color.",
           [chk("in_region", 4, "items within owner's reach", items=[
               {"text": t, "participant": who} for t, who in ACTIONS]),
            chk("property", 2, "items colored by owner", items=[
                {"text": t, "field": "color", "value": REACH[who]["color"]} for t, who in ACTIONS]),
            chk("preserve_human", 1, "item text unchanged"),
            chk("no_overlap", 1)])],
     [[call("move_elements", moves=_reach_moves)]
      + [call("update_element", id=find(t), color=REACH[who]["color"]) for t, who in ACTIONS]],
     initial=[frame("Action items", 1300, 1750, 1300, 500)]
     + [sticky(t, 1350 + 205 * i, 1850) for i, (t, _) in enumerate(ACTIONS)],
     participants=REACH,
     skills=["embodied ergonomics", "ownership", "spatial constraints"])

SPEECH = [("maya", "Um, so, okay, I think we should, like, pilot the new onboarding with just the EU region first."),
          ("sam", "Sorry, is anyone else's audio echoing? ... Okay, it's fine now."),
          ("lee", "The EU pilot makes sense, but we need the translated help docs ready before we start."),
          ("maya", "Right, and we should measure activation rate over the first two weeks."),
          ("sam", "I can own the dashboard for activation."),
          ("lee", "My coffee's getting cold, ha. Anyway, let's make sure support gets trained too.")]
KEYPOINTS = [("Pilot new onboarding in the EU region first", "pink", "pilot EU onboarding"),
             ("Translated help docs ready before the pilot", "green", "translated help docs"),
             ("Measure activation rate over the first two weeks", "pink", "activation rate two weeks"),
             ("Sam owns the activation dashboard", "blue", "activation dashboard"),
             ("Train the support team before launch", "green", "train support|support trained")]
task("xr_multi_speaker_capture", "xr_spatial", "Capture a noisy multi-speaker conversation", "medium", XR,
     [turn("Capture the key points from that exchange as stickies in the Discussion frame, one point per sticky, "
           "colored by who said it using each person's participant color. Leave out the small talk.",
           [chk("texts_present", 3, "key points captured", where={"frame": "Discussion"}, items=[k[2] for k in KEYPOINTS]),
            chk("texts_absent", 1, "small talk left out", items=["audio|echo", "coffee"]),
            chk("property", 2, "colored by speaker", items=[{"text": k[2], "field": "color", "value": k[1]} for k in KEYPOINTS]),
            chk("max_words", 0.5, selector={"type": "sticky"}, max=15),
            chk("in_frame", 1, selector={"author": "agent"}, frame="Discussion"),
            chk("no_overlap", 0.5)],
           events=[{"op": "say", "actor": f"human:{w}", "text": s} for w, s in SPEECH])],
     [[call("create_sticky", text=t, x=150 + 210 * i, y=200, color=c) for i, (t, c, _) in enumerate(KEYPOINTS)]],
     initial=[frame("Discussion", 100, 100, 1200, 800)],
     participants={k: PEOPLE[k] for k in ("maya", "sam", "lee")},
     skills=["speech capture", "speaker attribution", "filtering"])

LAYER_ITEMS = [("Option A: $9/month flat", 1), ("Option B: $5/month + usage", 1), ("Option C: Free tier + $15 Pro", 1),
               ("Competitor pricing notes", -1), ("Old meeting notes (March)", -1), ("Team lunch Friday?", 0),
               ("Hiring plan draft", 0)]
task("xr_focus_layers", "xr_spatial", "Use depth layers to focus the room", "easy", XR,
     [turn("We're focusing on the pricing decision now. Pull the three pricing options forward into the focus layer, "
           "push the reference material (the competitor notes and the old meeting notes) into the background, and "
           "leave everything else on the board surface. Then add a floating note in the focus layer that states the "
           "decision we need to make.",
           [chk("property", 4, "items on the right layers",
                items=[{"text": t, "field": "layer", "value": l} for t, l in LAYER_ITEMS]),
            chk("count", 1, "one focus note added", selector={"author": "agent", "layer": 1}, min=1, max=2),
            chk("texts_present", 1, "focus note states the decision", where={"author": "agent", "layer": 1},
                items=["decide|decision|choose|pick"], threshold=0.5),
            chk("rubric", 1, "decision framing (judge)", question="Does the new focus-layer note frame the pricing "
                "decision clearly, naming the options being chosen between?")])],
     [[call("update_element", id=find(t), layer=l) for t, l in LAYER_ITEMS if l != 0]
      + [call("create_sticky", text="Decide: which pricing model do we launch with, A, B, or C?", x=700, y=560,
              w=320, h=140, color="blue", layer=1)]],
     initial=[frame("Pricing workshop", 100, 100, 1400, 800)]
     + [sticky(t, 150 + 200 * (i % 6), 200 + 220 * (i // 6)) for i, (t, _) in enumerate(LAYER_ITEMS)],
     skills=["attention management", "3D affordances"])


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for old in OUT.glob("*.json"):
        old.unlink()
    for i, t in enumerate(TASKS, 1):
        (OUT / f"{i:02d}_{t['id']}.json").write_text(json.dumps(t, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {len(TASKS)} tasks to {OUT}")
