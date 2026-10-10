# 09. Stories

> Version: V1.0
>
> Status: Product Requirements Document
>
> Last Updated: August 2026

---

# 1. Purpose

Stories allow users to share temporary content that disappears after twenty-four (24) hours.

Unlike feed posts, Stories encourage casual and frequent sharing without permanently affecting a user's profile.

Stories increase daily engagement while helping businesses promote products, discounts, announcements, and events in real time.

---

# 2. Objectives

Stories should:

- Increase daily engagement.
- Encourage spontaneous sharing.
- Promote businesses naturally.
- Increase product discovery.
- Promote events.
- Keep the Home Feed uncluttered.

---

# 3. Who Can Create Stories

Students can create Stories.

Businesses can create Stories.

Administrators cannot create Stories through the Admin Panel.

---

# 4. Story Lifetime

Stories remain visible for:

```
24 Hours
```

After expiration:

- Stories disappear automatically.
- Story analytics remain available to businesses.
- Media is archived internally according to platform retention policies.

---

# 5. Story Placement

Stories appear at the top of the Home Feed.

```
Logo

Activity

Messages

-------------------------

Stories

-------------------------

Feed
```

Desktop displays the same Stories row above the feed.

---

# 6. Story Media

Supported media:

- Images
- Videos

Multiple story slides may be uploaded sequentially.

Each slide is treated as an individual Story.

---

# 7. Story Camera

Users may:

- Upload from Gallery
- Capture using Camera (future)
- Delete before publishing
- Rearrange slides

---

# 8. Story Editor

Before publishing, users may edit Stories.

Supported editing tools include:

- Crop
- Rotate
- Basic Filters
- Brightness
- Contrast

Version 1 intentionally excludes advanced photo editing.

---

# 9. Creative Tools

Stories support:

- Text
- Stickers
- Emoji
- Drawing
- Freehand Pen

These edits become part of the published Story.

---

# 10. Music

Stories support audio.

Available sources:

- Licensed music library
- Original audio
- Previously used sounds

Music licensing depends on availability within supported regions.

---

# 11. Mentions

Users may mention:

Students

Businesses

Mentioned accounts receive notifications.

Mentions open directly to the tagged profile.

---

# 12. Hashtags

Stories support hashtags.

Examples:

#FreshersWeek

#CampusLife

#BellsUniversity

Hashtags contribute to discovery where applicable.

---

# 13. Story Links

Businesses may attach:

- Product links
- Event links
- Website links

Students may attach:

- Profile mentions
- Public links (future)

Tapping a link opens the corresponding destination.

---

# 14. Product Stories

Businesses may link products directly within Stories.

Customers can:

- View Product
- Add to Cart
- Visit Business

without leaving the Story experience.

---

# 15. Event Stories

Businesses may promote events.

Stories may include:

- Event banner
- Countdown text
- Ticket link

Selecting the Story opens the Event Details page.

---

# 16. Viewing Stories

Users can:

- Tap to advance
- Tap left to go back
- Swipe to skip
- Pause by holding the screen

Stories automatically advance after a predefined duration.

---

# 17. Story Order

Stories appear in this general order:

1. Accounts the user follows.
2. Frequently interacted accounts.
3. Businesses the user engages with.
4. Recommended accounts.

Within each category, newer Stories appear before older ones.

---

# 18. Story Viewer List

Story owners can see:

- Viewer name
- Profile picture
- View timestamp

Businesses additionally receive aggregate metrics.

---

# 19. Story Reactions

Users may react using standard Unicode emojis.

Examples:

❤️

😂

🔥

👏

😍

Reactions are delivered privately.

---

# 20. Story Replies

Users may reply privately.

Replies become Direct Messages.

Businesses receive replies in the same messaging system.

---

# 21. Story Sharing

Stories cannot be reposted directly.

Users may instead:

- Share the profile
- Share linked products
- Share linked events

Future versions may support Story resharing.

---

# 22. Story Analytics

Businesses may view:

- Views
- Reach
- Replies
- Reactions
- Link clicks
- Product clicks
- Event clicks
- Completion rate

Students receive only viewer information.

---

# 23. Privacy

Version 1 uses public Stories.

Future versions may introduce:

- Close Friends
- Hide Story from specific users
- Story privacy controls

---

# 24. Reporting

Stories may be reported for:

- Spam
- Harassment
- Fraud
- Inappropriate content
- Copyright violations

Reported Stories enter the moderation queue.

---

# 25. Expiration

When Stories expire:

- They disappear from public view.
- Links become inactive.
- Analytics remain available.
- Internal records remain for moderation and audit purposes.

---

# 26. Performance

Stories should:

- Load progressively.
- Preload the next Story.
- Use adaptive media quality.
- Minimize buffering.
- Cache viewed Stories where appropriate.

---

# 27. Future Enhancements

Potential future additions:

- Story Highlights
- Polls
- Questions
- Quizzes
- Countdown stickers
- Location stickers
- Collaborative Stories
- Story templates
- AI-generated stickers

---

# 28. Summary

Stories provide a lightweight and engaging way for users and businesses to share temporary content.

By supporting creative tools, music, product links, and event promotions, Stories strengthen CartFlow's social layer while driving product discovery and business engagement without overwhelming the permanent Home Feed.

---

# Implementation Status — as built (August 16, 2026)

**Not built.** There is no `stories` table and no Media model, so nothing here has
storage behind it.

What exists today is the *shape* of it, on Home (`app/templates/home.html`): a
horizontal rail of story rings with the signed-in user first as "Your story", and
an in-page viewer with tap-through and progress bars. Both run entirely on the
curated placeholder list defined at the top of that template.

- **"Add to your story"** toasts rather than opening a composer — a composer would
  accept a photo and then drop it.
- **The `+` create sheet** in `app/templates/base.html` lists Story as waiting on
  `stories` + `media`, so tapping `+` tells you where the feature actually is.
- The 24-hour expiry, views list, replies, music, product links and event links
  (§5-§14) are all specified and unimplemented.

Stories land in the same slice as the content backend (posts, media, likes), not
before it.

---

# End of Document