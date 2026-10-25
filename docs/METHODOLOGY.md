# Methodology and Interpretation

SignalDesk treats every output as one of three classes:

- **Observed:** present directly in acquired public data.
- **Calculated:** reproducible aggregation or comparison.
- **Heuristic:** a screening signal requiring review.

## Corpus Scope

A report describes the collected sample. Its coverage depends on:

- search queries and seeds;
- date window;
- region and language ranking hints;
- API result limits;
- public metadata availability;
- user selection and exclusions.

It is not a census of a platform or market.

## Channel Metrics

Channel views and engagement are calculated over observed videos, not the channel's private analytics. A channel represented by one video has weaker evidence than a channel represented by ten videos.

## Semantic Profiles

The default engine builds TF-IDF vectors from channel descriptions, video titles, tags, and descriptions. Similarity is cosine similarity within the current pool. Scores are pool-relative and can change when the candidate set changes.

## Audience Overlap

Overlap uses pseudonymized authors found in acquired comments. It measures shared observed commenters, not shared viewers, followers, or subscribers.

## Commercial Signals

ADV analysis combines platform flags, disclosure phrases, affiliate URLs, promo codes, entity mentions, transcript evidence, and cross-content patterns. The output is evidence for review, not proof of a contract or legal conclusion.

## Integrity Signals

Anomaly scores use transparent thresholds, repeated normalized text, activity windows, and robust statistics. They prioritize investigation and do not classify users as bots.

## Geographic Signals

Channel country and language are optional creator-provided metadata. They may describe market settings rather than identity. Curated seed registries and textual evidence can supplement, but not fully replace, missing metadata.

## Data Handling

Public author identifiers are transformed into stable HMAC pseudonyms before persistence. Public reports should expose aggregate evidence rather than author-level identifiers.
