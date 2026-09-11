# https-initiativeforlegalaid.org-

Website study and admin-managed implementation for Initiative for Legal Aid.

## Project purpose

This project provides a public website for Initiative for Legal Aid with a simple admin dashboard that lets authorized users:

- update homepage text
- change contact details
- manage services/projects/testimonials
- upload hero and gallery images

## Local run

```bash
cd "/Users/freemirghani/Downloads/AIT ANALYSIS"
python3 app.py
```

Then open:

- http://localhost:5000/
- http://localhost:5000/admin/login

## Admin credentials

- Username: admin
- Password: admin123

> Change these before production deployment.

## Production URL

The live site should remain on:

https://initiativeforlegalaid.org/

To maintain that domain, deploy this Flask app to the server that hosts the domain and configure the web server to proxy traffic to the app.

## Deployment notes

- Set environment variables for the admin account and secret key
- Use HTTPS with the domain host or certificate manager
- Serve the app behind Nginx or Apache in production
