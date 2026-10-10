# 31. Deployment and Infrastructure

> Version: V1.0
>
> Status: Technical Documentation
>
> Last Updated: August 2026

---

# 1. Purpose

This document defines the deployment architecture and infrastructure required to run CartFlow reliably in production.

The infrastructure must provide:

- High availability
- Security
- Scalability
- Monitoring
- Automated deployments
- Disaster recovery

---

# 2. Deployment Goals

The infrastructure should:

- Support continuous deployment.
- Minimize downtime.
- Handle increasing traffic.
- Provide secure communication.
- Support future horizontal scaling.

---

# 3. Production Stack

Backend

FastAPI

Frontend

Jinja2 Templates

Database

PostgreSQL

Media Storage

Cloudinary

Background Jobs

Celery

Scheduler

APScheduler

Cache (Optional V1)

Redis

Reverse Proxy

Nginx

SSL

Let's Encrypt

Process Manager

systemd

Version Control

Git

Repository

GitHub

---

# 4. Infrastructure Overview

```
Internet

↓

Cloudflare (Future)

↓

Nginx

↓

FastAPI

↓

PostgreSQL

↓

Cloudinary

↓

Redis

↓

Celery Workers

↓

Email Provider

↓

Payment Provider
```

---

# 5. Environment Types

Development

Used locally.

Testing

Internal QA.

Staging

Pre-production environment.

Production

Live customer environment.

Each environment has independent configuration.

---

# 6. Server Structure

Recommended directories:

```
/home/cartflow/

app/

logs/

backups/

media/

venv/

.env
```

---

# 7. Environment Variables

Sensitive configuration is stored in:

```
.env
```

Examples:

Database URL

JWT Secret

Cloudinary Keys

Email Credentials

Payment Keys

Redis URL

Admin Secrets

Environment variables are never committed to Git.

---

# 8. Web Server

Nginx responsibilities:

HTTPS

Reverse Proxy

Static File Delivery

Compression

Security Headers

Request Logging

---

# 9. Application Server

FastAPI runs using:

Uvicorn

or

Gunicorn + Uvicorn Workers

Multiple workers improve concurrency.

---

# 10. SSL

Production uses HTTPS.

Certificates are managed using:

Let's Encrypt

Automatic renewal is configured.

---

# 11. Database

Production database:

PostgreSQL

Responsibilities:

Transactions

Relationships

Indexes

Constraints

Backups

---

# 12. Background Workers

Dedicated worker processes execute:

Emails

Notifications

Escrow

Story Expiration

Analytics

Receipt Generation

Cleanup Tasks

Workers run independently from the web server.

---

# 13. Redis

Version 1:

Optional

Primary uses:

Job Queue

Caching

Session Data (Future)

Rate Limiting

---

# 14. Media Storage

Media uploads are stored in:

Cloudinary

Only metadata and secure URLs are stored in PostgreSQL.

---

# 15. Logging

Logs include:

Application Logs

Access Logs

Error Logs

Background Worker Logs

Deployment Logs

Audit Logs

---

# 16. Monitoring

Monitor:

CPU

Memory

Disk

Database

Redis

Workers

API Response Time

Payment Gateway

Email Service

---

# 17. Deployment Strategy

Deployment steps:

Pull Latest Code

↓

Install Dependencies

↓

Run Database Migrations

↓

Restart Workers

↓

Restart FastAPI

↓

Health Check

↓

Deployment Complete

---

# 18. Continuous Deployment

Recommended workflow:

Developer Pushes Code

↓

GitHub

↓

GitHub Actions (Future)

↓

Server Deployment

↓

Health Checks

↓

Success Notification

---

# 19. Rollback

If deployment fails:

Restore previous release.

Restore previous migration (if applicable).

Restart services.

Notify administrators.

---

# 20. Database Backups

Daily automatic backups.

Backup types:

Full Backup

Incremental Backup (Future)

Backups are encrypted and stored securely.

---

# 21. Disaster Recovery

Recovery includes:

Application Restoration

Database Restoration

Media Verification

Worker Recovery

Configuration Recovery

---

# 22. Scaling Strategy

Growth path:

Single Server

↓

Separate Database Server

↓

Redis

↓

Multiple Workers

↓

Load Balancer

↓

Multiple API Servers

↓

Read Replicas

↓

Distributed Infrastructure

---

# 23. Static Assets

Static files include:

CSS

JavaScript

Fonts

Icons

These are served efficiently through Nginx.

---

# 24. Health Checks

Endpoints:

```
GET /health
```

Checks:

Application

Database

Redis

Workers

Cloudinary

Payment Gateway

Email Provider

---

# 25. Security

Infrastructure security includes:

Firewall

SSH Key Authentication

Automatic Security Updates

Fail2Ban

HTTPS

Rate Limiting

Secure Environment Variables

---

# 26. Domain

Production domain:

```
cartflow.africa
```

API domain:

```
api.cartflow.africa
```

Future:

```
admin.cartflow.africa

docs.cartflow.africa

developers.cartflow.africa
```

---

# 27. Infrastructure Metrics

Track:

Requests Per Minute

Concurrent Users

Database Size

Storage Usage

Bandwidth

Queue Length

Worker Utilization

API Latency

---

# 28. Maintenance

Regular maintenance tasks:

Security Updates

Database Optimization

Dependency Updates

Backup Verification

Certificate Renewal

Log Rotation

---

# 29. Future Infrastructure

Potential additions:

Docker

Kubernetes

Terraform

Cloudflare CDN

Object Storage

Read Replicas

Auto Scaling

Multi-region Deployment

---

# 30. Summary

The CartFlow deployment architecture provides a secure, scalable, and maintainable production environment capable of supporting the platform from its initial launch through future expansion.

By separating responsibilities across the web server, application server, database, background workers, and cloud storage, the infrastructure remains resilient, efficient, and ready for long-term growth.

---

# End of Document

📌 One recommendation I'd make before you launch

Since you're initially hosting on a single Hacom server, I'd organize your production services using systemd so every component runs independently.

Example:

cartflow-api.service
cartflow-celery.service
cartflow-scheduler.service
nginx.service
postgresql.service
redis.service

Benefits:

Services restart automatically if they crash.
Easier monitoring with systemctl status.
Cleaner deployment process.
Independent restarts (e.g., restarting the API won't interrupt background jobs).
Better preparation for future scaling.

For V1, this setup is simple, reliable, and much easier to manage than introducing Docker or Kubernetes before they're actually needed.