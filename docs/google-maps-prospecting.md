# Google Maps Prospecting

## Railway variables

Configure these variables in the Railway service:

- `GOOGLE_MAPS_BROWSER_KEY`: browser key for Maps JavaScript API. Restrict it by HTTP referrer to the production domain.
- `GOOGLE_PLACES_API_KEY`: server key for Places API (New). Restrict this key to the Places API.

Enable in Google Cloud:

1. Maps JavaScript API
2. Places API (New)

## Search modes

- **Rápida**: up to 4 expanded queries, 1 result page per query.
- **Profunda**: up to 10 expanded queries, 2 result pages per query.
- **Territorial**: up to 18 expanded queries, 3 result pages per query.

The service performs multiple requests concurrently, deduplicates places by Google Place ID and marks companies already present in CRM.

## CRM import

Selected places are imported with `registration_id = gplace:<PLACE_ID>`. This allows subsequent searches to recognize the same company and prevents duplicate discovery records.
