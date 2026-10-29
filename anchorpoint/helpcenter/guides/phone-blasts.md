A phone blast calls one person, or everyone in a group, and plays a recorded message: a
snow-day cancellation, a prayer request, a reminder. This guide shows you how to record
one, send it now or later, and see who answered. Plan on about **5 minutes**, most of it recording.

!!! note "Before you start"
    - **Your role:** You need an **Admin** login, or a login with **Can send SMS & calls**
      turned on (an Admin sets this under **Permissions**).
    - **Twilio is connected.** If the Communications page shows *Add Twilio credentials*,
      an Admin needs to do the one-time setup in
      [Sending text messages](/help/text-blasts/#one-time-setup-admins) first.
    - **A microphone**, or an audio file (MP3 or WAV) you've already recorded.

## Who gets the call

AnchorPoint only calls people who have **both**:

1. A **phone number** on their profile, and
2. **Phone opt in** ticked.

Phone opt in covers phone blasts as well as texts, even though the profile shows it as
*Texts: Can receive texts*. When you call a group, members without a phone number or
opt-in are left out automatically. AnchorPoint checks opt-in again when it dials. If someone opted out after
you scheduled the blast, they're skipped.

A group blast calls **everyone in the group** (leaders and members), each person
separately. If two people in the group share a phone number (a
family's home phone, for example), that number rings once for each of them.

## Send a phone blast to a group

1. Go to **Communications** and click **New phone blast**.
2. Leave **Send to** on **Group**, and pick the **Group** to call.
3. Type a **Title**. It's for your staff, not read aloud. For example, "Snow day: no
   rehearsal tonight".
4. Add your message under **Audio Message** (see
   [Record or upload your message](#record-or-upload-your-message)).
5. Leave **Call Time** blank to start calling now, or pick a date and time.
6. Optional: **Notes (internal)** are for staff only and are never played.
7. Click **Save & Launch**.

![The New phone blast form](communications/20-blast-form.png)

You go back to the Communications page with *Phone blast queued. It goes out within a
minute.*

!!! warning "Check who you picked before you launch"
    There's no cancel button, not even for a scheduled blast. Make sure you picked the
    right person or group and that your recording plays back correctly.

## Send a phone blast to one person

Use this for a personal voice message, like a thank-you or a check-in after a hospital
visit.

1. Go to **Communications** and click **New phone blast**.
2. Change **Send to** to **Individual person**.
3. In the **Person** box, type part of their name, email or phone number, then click
   the right person. Their row turns green.
4. Type a **Title**, add your **Audio Message**, and pick a **Call Time** if you want it
   later.
5. Click **Save & Launch**.

![Calling one person: search, pick them, then add the message](communications/22-blast-person.png)

Pressing Enter in the search box won't launch the call, so you can't send it by accident
while searching.

## Record or upload your message

You have two ways to add the message:

**Record it in the browser** (easiest, works on a phone or laptop):

1. Click **● Record**. Allow the microphone if your browser asks.
2. Speak your message. A timer counts up. Recording stops on its own at **3 minutes**.
3. Click **■ Stop**. A player appears so you can listen back.
4. Not happy with it? Click **↺ Re-record** and start again.

**Or upload a file:** click **Choose File** and pick an MP3 or WAV (M4A, OGG and WebM also
work). The file must be **10 MB or smaller**, a few minutes at most.

!!! tip "Recording tips"
    - Start with who's calling: "Hi, this is Pastor Sam from Harbor Community Church."
    - Keep it under a minute. Say the key detail (date, time, place) twice.
    - Record somewhere quiet, holding the phone or mic about a hand's width from your mouth.

## Schedule a phone blast for later

Pick a date and time in **Call Time** before clicking **Save & Launch**. The blast shows as
**Scheduled** on the Communications page and starts calling within a minute of that time.

- The time must be in the future.
- It can't fall inside your church's **blackout window** (quiet hours, for example
  9 PM to 8 AM). AnchorPoint won't let you launch or schedule calls in that window.

## See who answered

On the Communications page, click the blast's title under **Recent phone blasts**. The
page updates by itself while calls are going out.

![A finished phone blast: totals at the top, one row per call](communications/21-blast-detail.png)

At the top you can play the recording and see the totals. Below is one row per person:

| Status | Meaning |
|---|---|
| **Answered** | Someone picked up, or voicemail took the message. |
| **No Answer** | It rang out with no answer and no voicemail. |
| **Failed** | The line was busy, the number didn't work, or the call couldn't be placed. If AnchorPoint knows why, the reason shows under the name. |
| **Pending** | Still calling. |
| **Skipped** | Not called. *Opted out* means Phone opt in was off when the blast went out. |

The call also shows on each person's profile under **Communications History**.

Recordings are deleted **30 days** after a blast finishes. After that, the blast page says
*Recording removed* but keeps the call results.

## Troubleshooting

| You see | What it means | What to do |
|---|---|---|
| *Select the group you want to contact.* | No group was picked. | Pick a group. |
| *Select a person to send this message to.* | No person was clicked in the search results. | Search again and click their name. |
| *That person does not have a phone number.* | Their profile has no phone. | Add their number to the profile, then try again. |
| *This person has opted out of phone contact.* | Phone opt in isn't ticked. | Only tick it if they've agreed to calls and texts. |
| *Nobody in this group has a phone number with contact opt-in.* | No one in the group can be called. | Check the members' phone numbers and Phone opt in. |
| *Audio file is too large (max 10 MB). Record a shorter message.* | The file is over 10 MB. | Record a shorter message, or export a smaller MP3. |
| *Unsupported audio format. Upload an MP3 or WAV, or record in the browser.* | The file type isn't supported. | Use MP3 or WAV, or record in the browser. |
| *Microphone unavailable — upload a file instead.* | The browser can't use your mic. | Allow microphone access in the browser, or record on your phone and upload the file. |
| *You are inside the configured blackout window…* | It's quiet hours right now. | Pick a **Call Time** after the window ends. |
| A call shows **Failed** with *No status received* | Twilio never reported back on that call (checked after 2 hours). | Call that person yourself. If many calls show this, tell your Admin. |
| No **● Record** button | This browser can't record audio. | Upload a file instead, or try Chrome or Safari. |
