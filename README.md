# Cloud Storage Archival Framework

**Age-based archival of cold data in Google Cloud Storage: 104 TB moved to archival storage, saving about $45,000 per year.**

> This repository is a project write-up of work I owned end to end. The production scripts and configuration are internal and not published.

## The problem

A data platform kept years of files in Nearline and Coldline Cloud Storage buckets. Anything older than 13 months was almost never read, but it still cost money to store and to scan from BigQuery. Moving it by hand was not realistic: there were many buckets and prefixes, the volume was in terabytes, and it was production data that had to stay recoverable for audits.

## Approach

1. **Inventory:** list objects by prefix and pick those whose last-modified time is older than the retention cutoff (13 months).
2. **Plan in batches:** split the work into transfer jobs by bucket and prefix, and record each job in a tracking table so every batch is auditable and can be retried.
3. **Transfer:** a reusable Python service on top of **GCP Storage Transfer Service** creates and runs the jobs. It filters by last-modified time and moves objects into an archival bucket with **Autoclass** enabled, so storage class follows access patterns automatically.
4. **Roll out in phases:** run batch by batch over several phases, with sign-off between phases.

## Ownership

I owned this initiative end to end: the design, approvals, leadership updates, the production rollout, and the RCA.

## Results

- **104 TB** archived
- **~$45,000 per year** saved on storage and BigQuery costs
- A reusable, configuration-driven process for future archival runs

## Tech

Python · GCP Storage Transfer Service · Cloud Storage (Nearline, Coldline, Autoclass) · BigQuery · SQL
