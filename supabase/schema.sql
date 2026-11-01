-- Run this in the Supabase SQL editor, then run `uv run seed.py`.
create table if not exists customers (
    id text primary key,
    full_name text not null,
    email text not null unique,
    loyalty_tier text not null default 'standard'
);

create table if not exists products (
    sku text primary key,
    name text not null,
    category text not null,
    description text not null,
    price numeric(10, 2) not null check (price >= 0),
    stock integer not null default 0,
    final_sale boolean not null default false,
    specs jsonb not null default '{}'
);

create table if not exists orders (
    id text primary key,
    customer_id text not null references customers (id),
    sku text not null references products (sku),
    quantity integer not null default 1 check (quantity > 0),
    total numeric(10, 2) not null check (total >= 0),
    status text not null check (status in ('processing', 'shipped', 'delivered', 'cancelled')),
    tracking_number text,
    ordered_at timestamptz not null,
    delivered_at timestamptz
);
create index if not exists orders_customer_id_idx on orders (customer_id);

-- One return per order keeps a retried create_return from creating a duplicate.
create table if not exists returns (
    id uuid primary key default gen_random_uuid(),
    order_id text not null unique references orders (id),
    customer_id text not null references customers (id),
    reason text not null,
    status text not null default 'approved',
    created_at timestamptz not null default now()
);

create table if not exists support_tickets (
    id uuid primary key default gen_random_uuid(),
    customer_id text not null references customers (id),
    reason text not null,
    status text not null default 'open',
    created_at timestamptz not null default now()
);

create table if not exists policies (
    topic text primary key,
    body text not null
);

-- The agent uses the service role key and filters by customer in code. With RLS on
-- and no policies, the public anon key cannot read any of this data.
alter table customers enable row level security;
alter table products enable row level security;
alter table orders enable row level security;
alter table returns enable row level security;
alter table support_tickets enable row level security;
alter table policies enable row level security;
