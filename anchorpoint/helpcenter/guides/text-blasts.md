This guide shows you how to send a text message from AnchorPoint, to one person or to a
whole group, right away or at a time you pick. Sending a text takes about **2 minutes**.

!!! note "Before you start"
    - **Your role:** You need an **Admin** login, or a login with **Can send SMS & calls**
      turned on (an Admin sets this under **Permissions**). If you don't see
      **Communications** in the sidebar, ask an Admin.
    - **Twilio is connected.** If the Communications page shows *Add Twilio credentials*,
      an Admin needs to do the one-time setup at the end of this guide first.
    - **People can only get texts if they've said yes.** See the next section.

## Who can get a text

AnchorPoint only texts people who have **both**:

1. A **phone number** on their profile, and
2. **Phone opt in** ticked (on their profile it shows as *Texts: Can receive texts*).

Phone opt in is off for new people until someone ticks it. To change it, open the person,
click **Edit**, and tick or untick **Phone opt in**:

![The Phone opt in checkbox on the person form](communications/02-opt-in.png)

!!! warning "Only tick it when they've agreed"
    Phone opt in covers **texts and phone blasts**. Tick it only when the person has told
    you they want to hear from the church this way.

AnchorPoint checks opt-in again at the moment it sends. If someone opts out after you
scheduled a text, they're skipped.

## Where to start

Everything starts from **Communications** in the sidebar. You'll see your recent texts
and phone blasts, with **New text** at the top right:

![The Communications page: recent texts on the left, recent phone blasts on the right](communications/00-home.png)

## Send a text to one person

1. Go to **Communications** and click **New text**.
2. Leave **Send to** on **Individual person**.
3. In the **Person** box, type part of their name, email or phone number. Matching people
   appear underneath.
4. Click the right person. Their row turns green.
5. Type your message in **Text**.
6. Leave **Schedule** blank to send now, or pick a date and time (see
   [Schedule a text for later](#schedule-a-text-for-later)).
7. Click **Save & Send**.

![Texting one person: search, pick them, type the message](communications/10-text-person.png)

You go back to the Communications page with *Message queued. It goes out within a
minute.* Pressing Enter in the search box won't send the text, so you can't send it by
accident while searching.

!!! tip "Two people with the same name?"
    Each result shows the person's age, family and phone number. Use those to pick the
    right one.

## Send a text to a group

A group text goes to **everyone in the group** (leaders and members) who has a phone
number and Phone opt in. People without either are left out automatically.

1. Go to **Communications** and click **New text**.
2. Change **Send to** to **Group**.
3. Pick the group from the **Group** list. Only active groups are listed.
4. Type your message in **Text**.
5. Leave **Schedule** blank to send now, or pick a date and time.
6. Click **Save & Send**.

![Texting a whole group](communications/11-text-group.png)

Each person gets their own copy of the text. Replies go to the church's Twilio number,
not into AnchorPoint.

!!! tip "Need to text a few people who aren't a group?"
    Make a group for them under **Groups** (for example, "Easter Greeters"), then text
    that group. You can reuse it next time.

## Schedule a text for later

Pick a date and time in **Schedule** before clicking **Save & Send**. The text shows as
**Scheduled** on the Communications page and goes out within a minute of that time.
There's no cancel button for a scheduled text, so double-check it before you save.

- The time must be in the future.
- It can't fall inside your church's **blackout window** (quiet hours, for example
  9 PM to 8 AM). Pick a time outside it.
- If you leave Schedule blank **during** the blackout window, AnchorPoint stops you:
  schedule it for after the window ends.

## Check what was sent

- **Communications page:** each text shows **Queued**, **Scheduled**, **Sending**,
  **Completed**, or **Failed**.
- **The person's profile:** the **Communications History** card lists every text and phone
  blast sent to them, with who sent it and the message:

![Communications History on a person's profile](communications/12-history.png)

!!! note "Completed means it was handed to the phone network"
    AnchorPoint can't tell whether the text reached the phone. For proof of delivery, use a
    phone blast: it reports who answered.

## Troubleshooting

| You see | What it means | What to do |
|---|---|---|
| *That person does not have a phone number.* | Their profile has no phone. | Add their mobile number to the profile, then try again. |
| *This person has opted out of phone contact.* | Phone opt in isn't ticked. | Only tick it if they've agreed to texts. |
| *Nobody in this group has a phone number with contact opt-in.* | No one in the group can get texts yet. | Check the members' phone numbers and Phone opt in. |
| *You are inside the configured blackout window. Choose a later send time.* | It's quiet hours right now. | Pick a **Schedule** time after the window ends. |
| *This time falls inside your configured blackout window.* | Your scheduled time is during quiet hours. | Pick a different time. |
| *Schedule time must be in the future.* | The time you picked has passed. | Pick a later time. |
| *Add your Twilio SID, auth token, and phone number…* | Twilio isn't connected. | An Admin does the one-time setup below. |
| Someone says they didn't get it | They may have opted out, or have a landline or wrong number. | Check their phone number and Phone opt in. Look at **Communications History** on their profile. |

## One-time setup (Admins)

Do this once, before anyone sends a text or phone blast.

### Connect Twilio

AnchorPoint sends texts and calls through Twilio. Go to **Settings → Organization** and
scroll to **Communications**:

![Twilio and blackout settings](communications/01-twilio-settings.png)

1. **Twilio Account SID**: starts with **AC**. Copy it from Twilio Console → Account Info.
2. **Twilio Auth Token**: from the same place. Use the **Auth Token**, not an API key
   (an API key won't work for phone blasts).
3. **Messaging Phone Number**: your Twilio number, like +15551234567.
4. Click **Save Settings** at the bottom of the page.

### Set quiet hours

Set **Blackout Start** and **Blackout End** (for example 9:00 PM and 8:00 AM). Texts and
phone blasts never go out in that window. Scheduled ones wait until it ends. Leave both
blank for no quiet hours.

### Let staff send

Go to **Permissions** and turn on **Can send SMS & calls** for each person who should
send texts and phone blasts, then click **Save all changes**. Admins can always send.
