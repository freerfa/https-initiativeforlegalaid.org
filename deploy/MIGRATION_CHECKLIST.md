# WordPress → Flask content migration (Option A cutover)
# Source scraped 2026-09-14 from https://initiativeforlegalaid.org/ (live WP site).
# Target: paste into the Flask admin dashboard at /admin after first deploy.
# Tick each box as you migrate. Images: re-upload originals via dashboard (paths differ).

## Already matching (no action)
- [x] Site name / tagline / hero eyebrow / hero badges
- [x] About story, 3 values, mission + 3 mission cards
- [x] 4 core services, 3 projects, 3 testimonials
- [x] Address, both phones, gallery (6), CTA texts

## Gaps to fill on the Flask side
- [ ] Services 5+6 (WP has 6, Flask has 4):
  - [ ] "Civic and Legal Education" — "We provide community education programs to raise awareness of legal rights and responsibilities, empowering citizens to actively participate in governance."
  - [ ] "Research and Advocacy" — "Our ongoing research and advocacy work seeks to influence policy reforms and enhance legal frameworks, ensuring justice systems serve all citizens effectively."
  - How: /admin → Programs → add 2 service rows (title | text), upload images.
- [ ] Project 4 "Research Projects" — "In-depth studies that inform our strategies and response to legal challenges in South Sudan."
  - How: /admin → Programs → add 1 project row + image.
- [ ] Office hours "Monday to Friday, 8 AM to 5 PM" — Flask has no office-hours field.
  - How: append to contact section via a custom section, or add to footer (code change).
- [ ] Extra footer links "Latest News" — Flask footer has Home/About/Services/Log in/Register.
  - How: create a "Latest News" custom page (/admin → Custom content) then link it, or drop the link.
- [ ] Testimonial name cleanup (WP shows template leftovers "Rahul Sharma / Priya Sharma / Aman Verma" next to real names).
  - How: keep Flask's clean 3 (Amina L., John D., Sarah M.) — do NOT copy the leftovers.
- [ ] Cookie banner (WP has consent banner; Flask has none).
  - How: optional — add later if privacy policy requires it.
- [ ] contact@domain.com is a placeholder on BOTH sites — replace with the real inbox before launch.

## Media
- [ ] Download hero/gallery/testimonial originals from WP Media Library (or re-export), re-upload via /admin → Media.
- [ ] Favicon / logo if WP has one worth keeping.

## Go-live checks
- [ ] All 6 services + 4 projects render on homepage
- [ ] /login works (Free), /register creates users, /admin saves
- [ ] https://initiativeforlegalaid.org/ + https://www.initiativeforlegalaid.org/ both 200, redirect http→https
- [ ] Old WP host kept 48h for rollback; site.db backed up to /root/
