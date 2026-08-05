# 0002. Storage Queue buffer between webhook and raw blob write

Status: Accepted
Date: 2026-08-04

## Context

The HTTP-triggered webhook Function has two jobs with different urgency: acknowledge Monzo quickly
(or it retries, and repeated failures risk Monzo disabling the webhook), and durably persist the
transaction. Writing directly to Blob Storage inside the HTTP handler couples these — a transient
Blob throttling event or slow write would delay or fail the response to Monzo.

## Decision

Add an Azure Storage Queue between the HTTP Function and the raw Blob write. The HTTP Function
validates the request, enqueues the payload, and returns 200. A separate Queue-triggered Function
consumes the message and writes to `raw/`. Raw blobs are named deterministically by `transaction_id`
so at-least-once queue redelivery is naturally idempotent (a reprocessed message just overwrites the
same blob).

Storage Queue was chosen over Service Bus — this is a single-producer, single-consumer flow with no
need for sessions, dead-letter reason codes, or pub/sub; Storage Queue is materially cheaper and
already lives in the same Storage Account.

## Consequences

- Blob write failures retry automatically (via queue visibility timeout) and land in a poison queue
  after repeated failures, without custom retry code.
- A bug in the Blob-writing path can't turn into 5xx responses to Monzo, since that logic is no
  longer in the HTTP request path.
- Adds a second Function (Queue trigger) and a small amount of operational surface (poison queue
  monitoring) for a pipeline that, at personal transaction volume, would likely work almost as
  reliably with a direct write. Justified here primarily as a resilience pattern worth demonstrating,
  not because current volume demands it.
