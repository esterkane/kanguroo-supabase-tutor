-- Olist Brazilian E-Commerce (kaggle.com/datasets/olistbr/brazilian-ecommerce) in the disposable `lab` DB.
-- Run by scripts/import_olist.py after the raw CSVs are in schema olist_staging (all text columns).
-- Deliberately like a freshly imported customer database: primary and foreign keys, but no secondary
-- indexes, no grants to anon/authenticated and no RLS. Labs add (or forget) those themselves.
-- Timestamps stay `timestamp` (no time zone): the dataset does not state one.

drop schema if exists olist cascade;
create schema olist;
comment on schema olist is
  'Olist Brazilian E-Commerce dataset (real, anonymised, 2016-2018), typed. Source: kaggle.com/datasets/olistbr/brazilian-ecommerce';

create table olist.category_translation (
  product_category_name         text primary key,
  product_category_name_english text not null
);
insert into olist.category_translation
select product_category_name, product_category_name_english from olist_staging.category_translation;

create table olist.customers (
  customer_id        text primary key,           -- one per order (!), see customer_unique_id
  customer_unique_id text not null,              -- the actual person
  zip_code_prefix    text not null,
  city               text not null,
  state              char(2) not null
);
insert into olist.customers
select customer_id, customer_unique_id, customer_zip_code_prefix, customer_city, customer_state
from olist_staging.customers;

create table olist.sellers (
  seller_id       text primary key,
  zip_code_prefix text not null,
  city            text not null,
  state           char(2) not null
);
insert into olist.sellers
select seller_id, seller_zip_code_prefix, seller_city, seller_state from olist_staging.sellers;

create table olist.products (
  product_id            text primary key,
  product_category_name text,                    -- not every name has a translation row
  name_length           integer,                 -- CSV column: product_name_lenght (sic)
  description_length    integer,                 -- CSV column: product_description_lenght (sic)
  photos_qty            integer,
  weight_g              integer,
  length_cm             integer,
  height_cm             integer,
  width_cm              integer
);
insert into olist.products
select product_id, nullif(product_category_name, ''),
       nullif(product_name_lenght, '')::numeric::int, nullif(product_description_lenght, '')::numeric::int,
       nullif(product_photos_qty, '')::numeric::int, nullif(product_weight_g, '')::numeric::int,
       nullif(product_length_cm, '')::numeric::int, nullif(product_height_cm, '')::numeric::int,
       nullif(product_width_cm, '')::numeric::int
from olist_staging.products;

create table olist.orders (
  order_id                      text primary key,
  customer_id                   text not null references olist.customers,
  order_status                  text not null,
  order_purchase_timestamp      timestamp not null,
  order_approved_at             timestamp,
  order_delivered_carrier_date  timestamp,
  order_delivered_customer_date timestamp,
  order_estimated_delivery_date timestamp
);
insert into olist.orders
select order_id, customer_id, order_status, order_purchase_timestamp::timestamp,
       nullif(order_approved_at, '')::timestamp, nullif(order_delivered_carrier_date, '')::timestamp,
       nullif(order_delivered_customer_date, '')::timestamp, nullif(order_estimated_delivery_date, '')::timestamp
from olist_staging.orders;

create table olist.order_items (
  order_id            text not null references olist.orders,
  order_item_id       integer not null,          -- 1..n within the order
  product_id          text not null references olist.products,
  seller_id           text not null references olist.sellers,
  shipping_limit_date timestamp not null,
  price               numeric(10,2) not null,
  freight_value       numeric(10,2) not null,
  primary key (order_id, order_item_id)
);
insert into olist.order_items
select order_id, order_item_id::int, product_id, seller_id, shipping_limit_date::timestamp,
       price::numeric, freight_value::numeric
from olist_staging.order_items;

create table olist.order_payments (
  order_id             text not null references olist.orders,
  payment_sequential   integer not null,         -- an order can be paid in several parts
  payment_type         text not null,
  payment_installments integer not null,
  payment_value        numeric(10,2) not null,
  primary key (order_id, payment_sequential)
);
insert into olist.order_payments
select order_id, payment_sequential::int, payment_type, payment_installments::int, payment_value::numeric
from olist_staging.order_payments;

create table olist.order_reviews (
  id                      bigint generated always as identity primary key,  -- review_id repeats in the data
  review_id               text not null,
  order_id                text not null references olist.orders,
  review_score            smallint not null check (review_score between 1 and 5),
  review_comment_title    text,
  review_comment_message  text,
  review_creation_date    timestamp not null,
  review_answer_timestamp timestamp not null
);
insert into olist.order_reviews (review_id, order_id, review_score, review_comment_title, review_comment_message,
                                 review_creation_date, review_answer_timestamp)
select review_id, order_id, review_score::smallint, nullif(review_comment_title, ''),
       nullif(review_comment_message, ''), review_creation_date::timestamp, review_answer_timestamp::timestamp
from olist_staging.order_reviews;

create table olist.geolocation (                 -- no key: the source has many duplicate rows per zip prefix
  zip_code_prefix text not null,
  lat             double precision not null,
  lng             double precision not null,
  city            text not null,
  state           char(2) not null
);
insert into olist.geolocation
select geolocation_zip_code_prefix, geolocation_lat::float8, geolocation_lng::float8, geolocation_city,
       geolocation_state
from olist_staging.geolocation;

-- SYNTHETIC: Olist has no login identities. One deterministic fake user per real customer_unique_id, so
-- RLS lessons can set request.jwt.claims.sub to a user that owns real orders. Not part of the dataset.
create table olist.app_users (
  user_id            uuid primary key,
  customer_unique_id text not null unique,
  email              text not null unique
);
comment on table olist.app_users is
  'SYNTHETIC test identities (md5-derived uuid per customer_unique_id); not part of the Olist dataset';
insert into olist.app_users
select md5('olist:' || customer_unique_id)::uuid, customer_unique_id,
       'customer-' || left(customer_unique_id, 12) || '@example.test'
from (select distinct customer_unique_id from olist.customers) c;

analyze olist.category_translation, olist.customers, olist.sellers, olist.products, olist.orders,
        olist.order_items, olist.order_payments, olist.order_reviews, olist.geolocation, olist.app_users;
