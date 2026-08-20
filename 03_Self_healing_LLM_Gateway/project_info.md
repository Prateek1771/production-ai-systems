# PROJECT 3 - Self-Healing LLM Gateway (LLMOPS)
Tools - React js, Python, LiteLLM, FastAPI, Claude API, Redis, Prometheus, Grafana, Docker.  

### Why this project signals 
This is the project that reads as infrastructure rather than experimentation, which is exactly the transition you are trying to signal. It also gives you the strongest demo of the six, because you can break a provider live and show traffic rerouting on a dashboard while you talk.

## PHASE 1 
### Route every model call through one service
- Build a FastAPI service that accepts an OpenAI compatible request shape so existing clients need almost no change to adopt it.  
- Use LiteLLM to normalize provider differences. Configure at least three providers so failover has somewhere to go.  
- Require metadata on every request: tenant, feature, and request id. Without these you can never attribute cost, and cost attribution is half the value of a gateway.
## PHASE 2 
### Track health per provider 
- Maintain a rolling window per provider covering success rate, p50, p95, and p99 latency, and a proper error taxonomy separating rate limits, timeouts, server errors, content filters, and auth failures.  
- Keep counters in Redis using a sliding window so restarts do not reset your view of provider health.  
- Expose a /metrics endpoint for Prometheus. Instrument before you build failover, because failover logic you cannot observe is guesswork.
## PHASE 3 
### Fail over automatically
- Implement a circuit breaker per provider with closed, open, and half open states. Trip on error rate above threshold within the window, or p95 latency above budget.  - When a breaker opens, route to the next provider in the preference list for that request class. Preference lists differ by class, since a cheap classification call and a long form generation call should not fail over the same way.  
- Half open probes are what make it self healing. Send a small percentage of traffic back to a recovering provider, close the breaker if it succeeds, reopen immediately if it does not.
- For latency sensitive classes, add hedged requests: fire a second provider after N milliseconds, take whichever returns first, cancel the loser. Document the cost trade off, because hedging roughly doubles spend on hedged calls.
## PHASE 4 
### Queue and retry deferrable work  
- Classify requests as interactive or deferrable at the API boundary. Interactive calls fail fast, deferrable calls survive an outage.  
- Push deferrable work to a Redis queue with exponential backoff and jitter when every provider is degraded, instead of returning an error to the caller.  
- Attach idempotency keys so a retry cannot duplicate a side effect. This is the detail that signals you have operated something in production.
## PHASE 5 
### Put it on a Grafana board and then break it on purpose
- Panels worth building: requests per second by provider, error rate, p95 latency, circuit state timeline, failover events, queue depth, and cost per hour by tenant and by feature.  
- Add a chaos endpoint or proxy that injects errors and latency into one provider on demand.  
- Record a ninety second screen capture: healthy traffic, a provider degraded, the breaker tripping, traffic rerouting, and the breaker closing again as it recovers. 
- That video goes at the top of the README. It communicates more in ninety seconds than a page of architecture description.
### Done when 
You can degrade a provider live while traffic keeps flowing, and the dashboard shows the trip, the reroute, and the automatic recovery.
### Resume line:  
Built an LLM gateway with per provider circuit breaking and automatic failover; sustained X percent availability through simulated provider outages with per tenant cost attribution.
### Where this usually goes wrong  
- No cost attribution, which removes the main reason companies build gateways.  
- Retrying calls that are not idempotent, which turns a blip into duplicated side effects.  
- No half open state, so the breaker opens once and never heals.  
- A dashboard with no chaos test, which leaves the failover logic unproven.
### Stretch goals:  
Add a semantic cache layer, a model tiering router that sends easy requests to a small model, per tenant rate limits and budgets, and request logging with PII redaction.