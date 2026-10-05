This guide walks you through setting up children's check-in from scratch: rooms, a
check-in configuration, the kiosk, the label printer, and a test run. Plan on about
**45 minutes** for the first setup. After that, check-in runs on its own every week.

!!! note "Before you start"
    - **Your role:** You need an **Admin**, **Staff**, or **Volunteer Admin** login.
      Setting the kiosk PIN (Step 3) needs an **Admin**.
    - **A tablet or laptop** for the check-in station (an iPad works well).
    - **A label printer** set up with a print agent. If yours is already printing
      labels, skip Step 4.

## How check-in fits together

You set up three things once, and AnchorPoint handles each Sunday from there.

| Piece | What it is | Example |
|---|---|---|
| **Rooms** | The classrooms kids go to | Nursery, Toddlers, Preschool, Elementary |
| **Configuration** | *Who* can check in, *when* it's open, and *which rooms* | "Sunday Kids": up to 5th grade, Sundays 8:30–9:30 & 10:15–11:15 |
| **Kiosk** | The screen parents use to check in | An iPad at the welcome desk |

When a configuration's check-in time arrives, the kiosk opens it automatically. You
don't need to create anything each week. Each check-in prints a **name label** for the
child and a **pickup tag** for the parent, with a matching security code.

Everything starts from the **Check-In** page in the sidebar:

![The Check-In page: today's sessions at the top, setup links below](checkin-setup/00-dashboard.png)

## Step 1 — Add your rooms

1. Go to **Check-In → Rooms** and click **Add Room**.
2. Enter the **Name** (what parents and volunteers see, e.g. "Preschool").
3. Optional: **Building**, **Capacity**, and **Sort order** (lower numbers are listed first).
4. Optional but recommended: fill in **Auto-routing**. Set the ages and/or grades that
   belong in this room. At check-in, each child is pre-assigned to the matching room, and
   a parent or volunteer can still change it.
5. Click **Save Room**. Repeat for each room.

![Adding a room with its auto-routing ages and grades](checkin-setup/02-room-form.png)

!!! tip "How auto-routing picks a room"
    Grade wins over age. A 10-year-old in 5th grade goes to the room for 5th grade,
    even if another room's age range also covers 10. A child with no grade on file is
    matched by age. If nothing matches, the parent picks the room.

When you're done, your rooms list should look something like this:

![The rooms list](checkin-setup/01-rooms.png)

## Step 2 — Create a check-in configuration

A configuration is one kind of check-in, like "Sunday Kids", "Wednesday Youth", or
"VBS 2026". Most churches need just one to start.

Go to **Check-In → Configurations** and click **New Configuration**. The form has four
parts.

### Basic info

![Basic info: name, location, welcome message, and the checkout switch](checkin-setup/04a-config-basics.png)

- **Name**: shown to staff and printed on the labels (e.g. "Sunday Kids").
- **Location** and **Welcome message**: shown at the top of the kiosk screen.
- **Active**: leave this on. Turn it off to pause this check-in without deleting it.
- **Checkout**: turn this on if a volunteer checks pickup tags at the door when
  parents collect their kids. Leave it off if nobody staffs pickup. Pickup tags still
  print either way.

### Eligibility (who can check in)

![Eligibility filters: ages, grades, and groups](checkin-setup/04b-config-eligibility.png)

These settings decide who can be selected at the kiosk. Everyone else in the family
still shows up, but greyed out as "Not eligible".

- **Leave everything blank** and anyone can check in.
- **Ages and grades:** a child is eligible if they match the age range **or** the
  grade range. The example above lets in anyone age 11 or under, **or** anyone in
  Pre-K through 5th grade.
- **Groups:** members of the ticked groups can always check in, whatever their age.
  This is handy for adult volunteers or a specific class.
- **Auto-enroll group** (optional): everyone who checks in is added to this group. Use
  it for multi-day events like VBS, so walk-ins from day 1 show up on day 2's rosters.

!!! tip
    Ages and grades come from each person's profile. If a child shows as "Not eligible",
    their birthdate or grade is usually missing or out of date. Fix it on their profile.

### Schedule windows (when it's open)

![One schedule window: Sundays, check-in opens 8:30, closes 9:30](checkin-setup/04c-config-window.png)

Add one window for each service. Each window has four times:

- **Check-in opens**: the kiosk starts accepting check-ins.
- **Event starts**: when the service or class begins.
- **Check-in closes**: the kiosk stops accepting check-ins for this window.
- **Event ends**: when kids are picked up.

Pick **Recurring (weekly)** and a **Day of week** for something that happens every
week, or **Specific date** for a one-off (e.g. a Christmas Eve service). To add
another service, save the configuration and edit it again. A fresh blank window
appears at the bottom each time.

### Rooms

![Choose which rooms this check-in uses](checkin-setup/04d-config-rooms.png)

Tick the rooms kids can be sent to for this check-in, then click **Create
Configuration**.

## Step 3 — Set the kiosk PIN

The kiosk PIN stops anyone who walks up from opening check-in (and seeing family
names) on an unattended screen. **The kiosk won't open for the public until a PIN is
set.**

1. Go to **Settings → Organization** (Admins only).
2. Scroll to **Kiosk Security** and enter a 4–6 digit PIN.
3. Click **Save Settings**. Give the PIN to your check-in volunteers, not to parents.

![The Kiosk PIN setting](checkin-setup/05-kiosk-pin.png)

A kiosk stays unlocked for 12 hours, so a volunteer enters the PIN once on Sunday
morning. If you change the PIN, every kiosk locks right away.

## Step 4 — Connect the label printer

Labels print through a **print agent**. This is a small helper (usually a Raspberry Pi)
that sits next to the label printer and prints check-in labels automatically.

!!! note "Hand this one to your tech helper"
    Installing the print agent means typing one command on the Raspberry Pi. It's a
    one-time job of about 15 minutes. Whoever runs your AnchorPoint has the full
    walkthrough in the project docs. Your part is below.

    **For a Brother QL plugged in by USB**, tell them to use the `--brother-ql` option
    instead of `--printer-uri`. It talks to the printer directly and is much more reliable.

1. Go to **Check-In → Print agents**.
2. Type a name (e.g. "Front Desk Printer") and click **Add Agent**.
3. You'll get a **pairing code** and a setup command. Send both to your tech helper.
   The code expires after 15 minutes; click **New code** if it runs out.
4. Once it's installed, the agent shows **Online**. Set the **Label width** (62 for the
   common Brother 62mm roll) and click **Save**.
5. Click **Test Print**. A test label should come out within a few seconds.

![Print agents: one online, one waiting to be paired](checkin-setup/06-print-agents.png)

!!! tip "Label printing sideways or cut off?"
    Change **Rotation** and click **Save**. On a narrow continuous roll (like a Brother
    62mm), use **90°**. If labels then come out upside down, use **270°**.

## Step 5 — Set up the check-in station

On the tablet or laptop parents will use:

!!! warning "Don't sign in to AnchorPoint on the kiosk device"
    The kiosk only needs the PIN. If someone is signed in on that device, parents could
    reach the rest of AnchorPoint. If anyone has signed in there, click **Log out** first.

1. Open the web browser and go to your AnchorPoint address followed by
   **/checkin/kiosk/** (for example `https://yourchurch.org/checkin/kiosk/`).
   Bookmark it, or on an iPad use **Share → Add to Home Screen**.
2. Enter the **kiosk PIN** and tap **Unlock**.

![The kiosk asks for the PIN first](checkin-setup/07-kiosk-unlock.png)

3. If you have more than one printer, tap **Change** next to "Printer" at the bottom of
   the kiosk and pick the printer next to this station. **Automatic** is fine if you
   have just one.

![The kiosk's search screen. The printer choice is at the bottom.](checkin-setup/08-kiosk-search.png)

!!! tip "Lock the iPad to the kiosk"
    Turn on **Guided Access** (iPad **Settings → Accessibility → Guided Access**), open
    the kiosk, then triple-click the side or home button to start it. Parents can't
    leave the check-in screen until a volunteer triple-clicks and enters the Guided
    Access passcode.

Outside your schedule windows, the kiosk shows **"Check-In is Not Open"**. That's
expected.

## Step 6 — Do a test run

Do a test check-in before your first Sunday. If it isn't currently within a schedule
window, open check-in temporarily:

1. Edit your configuration. In the blank window at the bottom, choose **Specific
   date** and pick **today**. Fill in all four times: **Check-in opens** a few minutes
   ago, **Event starts** and **Check-in closes** about an hour from now, and **Event
   ends** a little after that. Click **Save Changes**.
2. On the kiosk, search for your own family (last name or phone number). Test
   check-ins count as real attendance, so use a family that won't mind.

![Search results](checkin-setup/09-kiosk-results.png)

3. Tap the family, tick the children, and check the room (it's pre-selected by
   auto-routing). Tap **Check In**.

![Pick who's checking in. Adults and anyone outside the eligibility settings are greyed out.](checkin-setup/10-kiosk-family.png)

4. The kiosk shows the **security code**, and labels print: one **name label** per
   child and one **pickup tag** for the parent.

![Check-in complete](checkin-setup/11-kiosk-done.png)

| Name label (on the child) | Pickup tag (parent keeps) |
|---|---|
| ![Sample name label](checkin-setup/label-child.png) | ![Sample pickup tag](checkin-setup/label-pickup.png) |

The child's label shows their name, room, the security code, and any **allergies**
(in red). The pickup tag has the same code. At pickup, the code on the parent's tag
must match the child's label.

5. **Clean up:** edit the configuration again and tick **Delete** on the test window,
   then **Save Changes**. Check the test children out from the Manager page (below).

## On Sunday morning

**Before doors open (5 minutes):**

1. Turn on the label printer (and its Raspberry Pi, if it's separate).
2. On the **Check-In** page, confirm the printer chip says **online**.
3. Open the kiosk on each station and enter the PIN.

**During check-in:** on the **Check-In** page, click **Manager** on today's session.
This is the live roster by room. From here you can:

- **Reprint** a lost or smudged label.
- See who's here in each room, and whether the printer is online.
- Click **Detail** to open a child's profile: allergies, notes, guardians (Staff and
  Admins only).

!!! tip "Volunteers without setup access"
    Volunteers with the plain **Volunteer** role can't open the Check-In page, but they
    *can* use the Manager and Checkout screens. Open those once on the volunteer's
    device (signed in as that volunteer) and bookmark them. The links change each
    session, so do this each week.

![The Check-in Manager: who's here, by room](checkin-setup/12-manager.png)

**At pickup (if Checkout is turned on):** click **Checkout** on today's session (or use
the volunteer's bookmark), type the code from the parent's pickup tag, and confirm
which children are going home.

**New families:** tap **I'm New Here** on the kiosk. The parent enters their details
and their children's, then picks who's checking in like any other family. Look over new families in
**People** afterwards.

## Troubleshooting

| What you see | What to do |
|---|---|
| Kiosk says **"Kiosk not configured"** | No PIN is set yet. See Step 3. |
| Kiosk says **"Check-In is Not Open"** | It's outside every schedule window. Check the configuration's days and times, and that the configuration and window are both **Active**. |
| A child is **greyed out / "Not eligible"** | Their birthdate or grade is missing or outside the configuration's eligibility. Update their profile, or add them to an eligible group. |
| The kiosk shows a list of check-ins to pick from | Two configurations are open at once. Pick one, or adjust the schedules so they don't overlap. |
| **No room** is pre-selected | No room's auto-routing range matches that child. Pick a room by hand, or adjust the room's ages and grades. |
| Labels don't print | On **Check-In → Print agents**, check the agent is **Online** and try **Test Print**. If it's **Offline**, restart the printer and the Raspberry Pi. Volunteers can reprint from the **Manager** once it's back. |
| Labels print sideways, cut off, or upside down | Adjust **Rotation** (and **Label width**) on the print agent, then **Test Print**. |
| A family can't be found | Search by phone number instead of last name, or use **I'm New Here**. |
