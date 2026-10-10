# 21. Database Schema

> Version: V1.0
>
> Status: Technical Documentation
>
> Last Updated: August 2026

---

# 1. Purpose

The CartFlow database stores all application data including users, businesses, products, orders, payments, events, social interactions, messaging, notifications, analytics, and administrative records.

The schema is designed to be:

- Relational
- Normalized
- Scalable
- Secure
- Audit-friendly
- API-first

The production database uses PostgreSQL.

---

# 2. Design Principles

The schema follows these principles:

- UUID primary keys
- Foreign key constraints
- Soft deletes where appropriate
- Timestamp auditing
- Minimal redundancy
- Proper indexing
- Transaction safety

---

# 3. Naming Conventions

Tables

snake_case

Example:

users

order_items

event_tickets

Columns

snake_case

Example:

created_at

updated_at

delivery_method

Foreign Keys

Singular table name + _id

Example:

user_id

business_id

order_id

---

# 4. Core User Tables

## users

Stores every account.

Columns

id

username

email

password_hash

account_type

full_name

bio

website

university_id

profile_photo

cover_photo

is_verified

status

created_at

updated_at

deleted_at

---

## universities

Stores Nigerian universities.

Columns

id

name

short_name

state

ownership

created_at

---

## follows

Stores follow relationships.

Columns

id

follower_id

following_id

created_at

---

# 5. Business Tables

## businesses

Stores business profiles.

Columns

id

owner_id

business_name

username

logo

bio

website

status

response_time

created_at

updated_at

---

## business_locations

id

business_id

current_location

pickup_location

updated_at

---

## business_delivery_areas

id

business_id

coverage_name

coverage_type

---

# 6. Product Tables

## products

id

business_id

category_id

name

slug

description

price

quantity

status

created_at

updated_at

---

## product_images

id

product_id

image_url

display_order

---

## product_categories

id

name

slug

---

## product_reviews

id

product_id

user_id

rating

review

created_at

---

## product_tags

id

product_id

tag_name

---

# 7. Feed Tables

## posts

id

author_id

caption

media_type

visibility

created_at

---

## post_media

id

post_id

media_url

media_order

---

## comments

id

post_id

user_id

parent_comment_id

comment

created_at

---

## likes

id

user_id

post_id

created_at

---

## saves

id

user_id

post_id

---

## reposts

id

user_id

post_id

---

# 8. Stories

## stories

id

user_id

media_url

expires_at

created_at

---

## story_views

id

story_id

viewer_id

created_at

---

# 9. Messaging

## conversations

id

created_at

---

## conversation_participants

conversation_id

user_id

---

## messages

id

conversation_id

sender_id

message_type

content

created_at

---

## message_attachments

id

message_id

attachment_url

attachment_type

---

# 10. Notifications

## notifications

id

user_id

type

title

body

is_read

created_at

---

## notification_preferences

id

user_id

settings_json

---

# 11. Cart

## carts

id

user_id

created_at

---

## cart_items

id

cart_id

product_id

quantity

delivery_method

---

# 12. Orders

## orders

id

customer_id

business_id

status

payment_status

escrow_status

delivery_method

total_amount

created_at

---

## order_items

id

order_id

product_id

quantity

price

---

## order_status_history

id

order_id

status

created_at

---

# 13. Payments

## payments

id

order_id

provider

reference

amount

status

created_at

---

## escrow_transactions

id

payment_id

status

release_date

released_at

---

## payouts

id

business_id

payment_id

amount

status

created_at

---

## refunds

id

payment_id

amount

reason

status

---

# 14. Business Banking

## business_bank_accounts

id

business_id

bank_code

bank_name

account_number

account_name

verified

---

# 15. Events

## events

id

business_id

title

slug

description

venue

start_time

end_time

ticket_price

ticket_quantity

status

---

## tickets

id

event_id

ticket_number

qr_code

status

---

## ticket_holders

id

ticket_id

full_name

email

phone

---

## ticket_scans

id

ticket_id

scanned_by

scanned_at

---

# 16. Reports

## reports

id

reporter_id

target_type

target_id

reason

status

created_at

---

# 17. Admin

## admin_users

id

email

password_hash

role

created_at

---

## audit_logs

id

admin_id

action

resource

resource_id

created_at

---

## error_logs

id

service

severity

request_id

message

stack_trace

resolved

created_at

---

# 18. Analytics

## analytics_events

id

event_type

user_id

resource_id

metadata

created_at

---

## daily_metrics

id

metric_name

metric_value

metric_date

---

# 19. Background Jobs

## background_jobs

id

job_name

status

attempts

started_at

completed_at

---

# 20. Soft Deletes

Tables supporting soft delete include:

- users
- businesses
- products
- posts
- events

Records remain recoverable until permanently purged.

---

# 21. Indexing Strategy

Indexes should exist on:

- usernames
- emails
- business usernames
- product slugs
- event slugs
- foreign keys
- created_at
- status columns

Composite indexes should be used for:

- feeds
- search
- recommendations
- analytics

---

# 22. Relationships

Examples:

User

↓

Business

↓

Products

↓

Orders

↓

Payments

↓

Escrow

↓

Payouts

Users

↓

Posts

↓

Comments

↓

Likes

↓

Reposts

Businesses

↓

Events

↓

Tickets

↓

Ticket Scans

---

# 23. Constraints

Use:

Foreign Keys

Unique Constraints

Check Constraints

NOT NULL where required

ON DELETE rules

---

# 24. Migrations

All schema changes are managed through Alembic migrations.

Every migration should be:

- Version controlled
- Reversible
- Tested before deployment

---

# 25. Performance

The database should:

- Use connection pooling.
- Optimize queries with indexes.
- Archive historical data where appropriate.
- Use pagination for large result sets.

---

# 26. Backup & Recovery

Backups should include:

- Daily automated backups
- Point-in-time recovery (if supported)
- Disaster recovery procedures

Backups should be encrypted and regularly tested.

---

# 27. Summary

The CartFlow database schema provides the structural foundation for the entire platform.

Its normalized PostgreSQL design ensures data integrity, scalability, and maintainability while supporting social networking, commerce, ticketing, messaging, payments, analytics, and future platform expansion.

---

# End of Document