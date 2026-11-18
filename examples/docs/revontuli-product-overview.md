# Revontuli - Product Overview

Revontuli is a route optimization service for delivery and logistics companies, built by
Lumikko Demo Oy. Both the company and the product are fictional; this document is demo
material for the localrag project.

## What Revontuli does

Revontuli takes a list of delivery stops, vehicles and constraints, and returns an
optimized plan: which vehicle visits which stops, in which order and at what time.
Typical customers cut their driven kilometres by 10-20 % in the first three months.

Supported constraints include delivery time windows, vehicle capacity (weight and volume),
driver working hours and break rules, and vehicle types such as refrigerated trucks.

## Coverage

Revontuli currently supports routing in Finland, Sweden, Norway and Estonia. Support for
Denmark is planned for the second half of 2027.

## Limits

- A single optimization request can contain up to 2,000 stops and 150 vehicles.
- Typical optimization time for 500 stops is under 30 seconds.
- Route plans and uploaded stop data are retained for 90 days and then deleted.

## API

Revontuli is used through a REST API or the web interface. Every customer gets separate
API keys for production and testing.

The API rate limit is 600 requests per minute per API key. Requests above the limit receive
HTTP status 429 and should be retried with exponential backoff.

Webhooks notify the customer system when a long-running optimization has finished.

## Pricing

| Plan | Price | Included |
| --- | --- | --- |
| Basic | 990 EUR / month | up to 5 vehicles, email support |
| Pro | 2,400 EUR / month | up to 40 vehicles, phone support |
| Enterprise | from 4,200 EUR / month | unlimited vehicles, SLA, dedicated contact |

## Roadmap

Revontuli 3.0 brings live re-optimization when traffic conditions change during the day.
See the steering group minutes for the current release schedule.
