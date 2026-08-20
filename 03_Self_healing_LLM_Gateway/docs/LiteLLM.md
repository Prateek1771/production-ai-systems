## LiteLLM — in depth

**LiteLLM is an open-source LLM gateway and Python SDK that gives your application a common interface for calling many different LLM providers.** It currently supports 100+ LLMs/providers and can normalize their inputs and outputs into an OpenAI-compatible format. ([LiteLLM][1])

The easiest mental model is:

> **LiteLLM is an API Gateway specifically designed for LLMs.**

If you have worked with Nginx, Kong, or an API Gateway, the architecture will feel familiar.

---

# 1. The problem LiteLLM solves

Suppose you are building an AI application.

Initially, you might use OpenAI:

```text
Your Backend
     |
     v
 OpenAI API
     |
     v
   GPT
```

Your code might look conceptually like:

```python
client.chat.completions.create(
    model="some-openai-model",
    messages=messages
)
```

Then you decide to support Claude.

Now you have:

```text
Your Backend
     |
     +----> OpenAI SDK ----> OpenAI
     |
     +----> Anthropic SDK -> Anthropic
```

Then Gemini:

```text
Your Backend
     |
     +----> OpenAI SDK ------> OpenAI
     |
     +----> Anthropic SDK ---> Anthropic
     |
     +----> Google SDK ------> Gemini
```

Then Mistral, Azure OpenAI, AWS Bedrock, Groq, Vertex AI, Ollama, etc.

The complexity starts increasing.

Different providers have:

* different authentication
* different endpoints
* different request formats
* different response formats
* different error types
* different streaming implementations
* different model names
* different rate limits
* different pricing
* different capabilities

LiteLLM provides an abstraction layer over this.

```text
                    ┌── OpenAI
                    ├── Anthropic
                    ├── Gemini
Your Application --> LiteLLM ├── Mistral
                    ├── Azure
                    ├── Bedrock
                    ├── Groq
                    └── Ollama
```

LiteLLM handles provider-specific communication and normalization. ([LiteLLM][1])

---

# 2. LiteLLM has TWO major forms

This distinction is extremely important.

LiteLLM isn't just one thing.

It has:

### A. LiteLLM Python SDK

You install it inside your application:

```text
Your Python Application
        |
        v
   LiteLLM SDK
        |
        +----> OpenAI
        +----> Anthropic
        +----> Gemini
        +----> etc.
```

### B. LiteLLM Proxy / AI Gateway

You run LiteLLM as a separate server:

```text
                 ┌── OpenAI
                 ├── Anthropic
Your Apps ──> LiteLLM Gateway ──> Gemini
                 ├── Mistral
                 └── Bedrock
```

The official documentation describes these as separate usage modes: SDK for developers integrating directly into an application, and Proxy Server for centralized gateway/organizational use. ([LiteLLM][1])

---

# 3. LiteLLM SDK

The SDK is the simpler part.

You can install LiteLLM and call models through it.

Conceptually:

```python
from litellm import completion

response = completion(
    model="openai/...",
    messages=[
        {
            "role": "user",
            "content": "Explain distributed systems"
        }
    ]
)
```

You can then change the provider/model without completely changing your application's LLM integration.

For example:

```text
openai/...
anthropic/...
gemini/...
mistral/...
```

The SDK handles the provider-specific transformation underneath.

---

# 4. What actually happens internally?

This is where LiteLLM becomes interesting.

Suppose your application sends:

```text
POST /chat/completions
```

with an OpenAI-style request:

```json
{
  "model": "some-model",
  "messages": [
    {
      "role": "user",
      "content": "Hello"
    }
  ]
}
```

LiteLLM needs to determine:

```text
Which provider?
Which endpoint?
How should the request be transformed?
How should the response be transformed?
```

Internally, the SDK roughly follows:

```text
Application
     |
     v
LiteLLM completion()
     |
     v
Determine provider
     |
     v
Provider-specific handler
     |
     v
Transform request
     |
     v
HTTP request
     |
     v
LLM Provider
     |
     v
Raw provider response
     |
     v
Transform response
     |
     v
Standardized response
     |
     v
Application
```

The architecture separates provider resolution, HTTP handling, provider-specific transformations, streaming handling, and callbacks. ([GitHub][2])

---

# 5. The translation layer

This is one of LiteLLM's most important pieces.

Imagine OpenAI expects:

```json
{
  "messages": [...],
  "model": "..."
}
```

while another provider has a different schema.

LiteLLM transforms:

```text
Your standardized request
          |
          v
     LiteLLM
          |
          v
Provider-specific request
```

Then the response comes back:

```text
Provider response
       |
       v
   LiteLLM
       |
       v
Standard response
```

So:

```text
           Translation
              Layer
                |
                v

OpenAI format <----> LiteLLM <----> Provider format
```

The provider-specific implementations contain request and response transformation logic. ([GitHub][2])

This is why your application doesn't need to understand every provider's API format.

---

# 6. LiteLLM Proxy

Now we get to the more powerful part.

Instead of installing LiteLLM directly inside your application, you can deploy it as an **LLM Gateway**.

Architecture:

```text
                       ┌───────────────┐
                       │    OpenAI     │
                       └───────▲───────┘
                               │
                       ┌───────┴───────┐
                       │   Anthropic   │
                       └───────▲───────┘
                               │
                       ┌───────┴───────┐
                       │    Gemini     │
                       └───────▲───────┘
                               │
                        LiteLLM Gateway
                               ▲
                               │
                ┌──────────────┼──────────────┐
                │              │              │
              App A          App B          App C
```

Your applications don't need individual provider credentials.

Instead:

```text
Applications
      |
      v
LiteLLM
      |
      v
Provider APIs
```

The gateway provides authentication, authorization, rate limiting, budgets, routing, logging and cost management around the underlying SDK. ([GitHub][3])

---

# 7. Why would a company use this?

Imagine a company has 50 developers.

They have:

```text
OpenAI
Anthropic
Gemini
Azure OpenAI
AWS Bedrock
Mistral
```

Without a gateway:

```text
Developer 1 ──> OpenAI
Developer 2 ──> Anthropic
Developer 3 ──> Gemini
Developer 4 ──> OpenAI
...
```

The company now has credentials scattered across many applications.

With LiteLLM:

```text
                  ┌── OpenAI
                  ├── Anthropic
Applications ---> LiteLLM ---> Gemini
                  ├── Azure
                  └── Bedrock
```

The company can centralize:

* authentication
* API keys
* budgets
* model access
* rate limits
* logging
* cost tracking
* routing
* fallbacks

This is one of the primary purposes of the Proxy Server. ([LiteLLM][1])

---

# 8. Virtual API keys

This is another important feature.

Suppose you don't want developers to receive your actual OpenAI API key.

Instead:

```text
Developer
   |
   | sk-project-123
   v
LiteLLM
   |
   | actual provider key
   v
OpenAI
```

The developer only knows the LiteLLM key.

LiteLLM can associate that key with:

```text
User
Project
Team
Budget
Allowed models
Rate limits
```

So you can have:

```text
Project A
    |
    +-- API key
    +-- $100 budget
    +-- GPT allowed
    +-- Claude allowed

Project B
    |
    +-- API key
    +-- $50 budget
    +-- Gemini allowed
```

This is particularly useful in internal AI platforms.

---

# 9. Cost tracking

LLMs cost money.

Suppose you have:

```text
Application A → $120
Application B → $75
Application C → $320
```

LiteLLM can track usage and spend across users/projects. The proxy supports spend tracking and budgets. ([LiteLLM][1])

Conceptually:

```text
                    LiteLLM
                       |
             ┌─────────┼─────────┐
             ↓         ↓         ↓
          Team A     Team B    Team C
           $120       $75       $320
```

This becomes useful when an organization has many AI applications.

---

# 10. Budgets

You can define limits.

For example:

```text
Team: AI Research

Monthly budget:
$500
```

Once usage approaches/exceeds the configured limit, the gateway can enforce the relevant budget controls.

This prevents one application from accidentally spending thousands of dollars.

---

# 11. Rate limiting

Imagine an API has:

```text
100 requests/minute
```

but your application has:

```text
1000 users
```

You can use LiteLLM as the control point:

```text
Users
  |
  v
LiteLLM
  |
  +-- Rate limit
  |
  +-- Authentication
  |
  +-- Budget check
  |
  v
LLM
```

The gateway supports rate limiting and usage controls. ([GitHub][3])

---

# 12. Routing

This is one of LiteLLM's most powerful features.

Suppose you have:

```text
GPT deployment #1
GPT deployment #2
GPT deployment #3
```

Instead of sending everything to one endpoint:

```text
             ┌── GPT #1
LiteLLM ─────┼── GPT #2
             └── GPT #3
```

LiteLLM can route/load-balance requests across deployments.

Its Router handles load balancing, retries, cooldowns and fallbacks. ([GitHub][4])

---

# 13. Fallbacks

Imagine:

```text
Primary:
GPT deployment
```

fails because of:

```text
rate limit
timeout
provider outage
```

You can configure a fallback:

```text
Request
   |
   v
GPT
   |
   X
   |
   v
Claude
```

Or:

```text
Request
   |
   v
OpenAI
   |
   X
   |
   v
Azure OpenAI
   |
   X
   |
   v
Anthropic
```

This improves availability.

---

# 14. Retry logic

Suppose:

```text
Request → Provider
             |
             X timeout
```

Instead of immediately returning an error:

```text
LiteLLM
   |
   ├── retry
   ├── retry
   └── fallback
```

LiteLLM's routing layer supports retry/fallback behavior and can use cooldown mechanisms to avoid repeatedly sending requests to unhealthy deployments. ([GitHub][4])

---

# 15. Load balancing

Consider:

```text
Model A
  RPM = 100

Model B
  RPM = 100

Model C
  RPM = 100
```

You effectively have more capacity available:

```text
                 LiteLLM
                /   |   \
               /    |    \
             A      B      C
```

The Router can distribute requests across deployments and track relevant usage/limits. Redis can be used for shared tracking in production deployments. ([GitHub][4])

---

# 16. Observability

LLM applications are difficult to debug.

A request might look like:

```text
User
 ↓
Frontend
 ↓
Backend
 ↓
RAG
 ↓
LLM
 ↓
Tool
 ↓
LLM
```

You want to know:

```text
Which model?
How many tokens?
How much did it cost?
How long did it take?
Did it fail?
What provider?
Which user?
Which project?
```

LiteLLM supports callbacks/integrations for observability systems such as Langfuse, MLflow and others. ([LiteLLM][1])

So you can build:

```text
Application
     |
     v
LiteLLM
     |
     ├── LLM
     |
     └── Observability
          ├── logs
          ├── latency
          ├── tokens
          ├── cost
          └── errors
```

---

# 17. Caching

LLM calls can be expensive.

Imagine:

```text
User:
"What is CAP theorem?"
```

and 500 users ask exactly the same thing.

Without caching:

```text
500 requests → LLM
```

With caching:

```text
Request
  |
  v
Cache?
 / \
yes no
 |   |
return LLM
```

LiteLLM includes caching functionality, and its gateway architecture uses caching infrastructure for things such as rate-limit state and LLM response caching. ([GitHub][2])

---

# 18. Streaming

LLMs usually stream responses:

```text
Hello
Hello, how
Hello, how are
Hello, how are you?
```

Instead of waiting for the entire response.

LiteLLM supports streaming and normalizes streaming behavior across providers. ([LiteLLM][1])

Architecture:

```text
User
 ↓
Your Backend
 ↓
LiteLLM
 ↓
Provider
 ↓
token
token
token
token
 ↓
Your UI
```

---

# 19. Error normalization

Different providers return different errors.

For example:

```text
OpenAI:
429 RateLimitError

Anthropic:
some other error format

Google:
another error format
```

Your application doesn't want:

```python
if openai_error:
    ...

if anthropic_error:
    ...

if google_error:
    ...
```

LiteLLM provides standardized error handling around provider calls. ([LiteLLM][1])

Conceptually:

```text
OpenAI Error
Anthropic Error
Gemini Error
      ↓
   LiteLLM
      ↓
Standardized error
```

---

# 20. What does the architecture look like?

A simplified production architecture:

```text
                         Internet
                            |
                            v
                    ┌───────────────┐
                    │ Load Balancer │
                    └───────┬───────┘
                            |
                            v
                 ┌─────────────────────┐
                 │   LiteLLM Gateway   │
                 │                     │
                 │ Authentication      │
                 │ Authorization       │
                 │ Rate Limiting       │
                 │ Routing             │
                 │ Fallback            │
                 │ Cost Tracking       │
                 │ Logging             │
                 │ Caching             │
                 └─────────┬───────────┘
                           |
              ┌────────────┼─────────────┐
              ↓            ↓             ↓
           OpenAI      Anthropic       Gemini
              ↓            ↓             ↓
           GPT/etc      Claude        Gemini
```

In larger deployments, LiteLLM can use infrastructure such as **Redis** for shared caching/rate-limit/usage state and **PostgreSQL** for persistent gateway data such as keys, teams and spend logs. ([GitHub][3])

---

# 21. SDK vs Proxy

This is probably the most important distinction to remember.

| Feature                | LiteLLM SDK    | LiteLLM Proxy                |
| ---------------------- | -------------- | ---------------------------- |
| Form                   | Python library | Server                       |
| Runs inside app        | Yes            | No                           |
| Multi-provider         | Yes            | Yes                          |
| Unified API            | Yes            | Yes                          |
| Routing                | Yes            | Yes                          |
| Fallback               | Yes            | Yes                          |
| Cost tracking          | Yes            | Yes                          |
| Central authentication | Limited        | Yes                          |
| Virtual keys           | No/limited     | Yes                          |
| Team management        | No             | Yes                          |
| Central budgets        | No             | Yes                          |
| Central rate limiting  | No             | Yes                          |
| Admin gateway          | No             | Yes                          |
| Best for               | Developers     | Organizations/platform teams |

The official docs make essentially this distinction: SDK for direct application integration, Proxy for centralized AI gateway functionality. ([LiteLLM][1])

---

# 22. LiteLLM vs OpenRouter

These are related but conceptually different.

### OpenRouter

Think:

```text
Your App
   ↓
OpenRouter
   ↓
Many LLM providers
```

It is primarily a **hosted model-routing service**.

### LiteLLM

Think:

```text
Your App
   ↓
Your LiteLLM Gateway
   ↓
Your provider accounts
```

You can self-host it and control the gateway infrastructure.

So LiteLLM is particularly attractive when you want:

```text
control
+
self-hosting
+
internal authentication
+
organization-wide governance
```

---

# 23. LiteLLM vs LangChain

These are also often confused.

They solve different problems.

### LiteLLM

Primarily:

```text
LLM infrastructure / gateway
```

### LangChain

Primarily:

```text
LLM application framework
```

For example:

```text
LangChain
   |
   ├── Prompt
   ├── Agent
   ├── Tool
   ├── Memory
   └── Retrieval
          |
          v
       LiteLLM
          |
       ┌──┴──┐
       ↓     ↓
     GPT   Claude
```

They can be used together.

---

# 24. LiteLLM vs an API Gateway like Kong

A traditional gateway:

```text
Client
  ↓
Kong
  ↓
Microservices
```

LiteLLM:

```text
Application
  ↓
LiteLLM
  ↓
LLM Providers
```

LiteLLM is specialized for LLM-specific concerns such as:

* model routing
* token usage
* model costs
* LLM fallbacks
* provider normalization
* LLM observability
* LLM-specific rate limits

That's why calling it an **LLM Gateway** is more accurate than simply calling it an API proxy.

---

# 25. How the request flows through LiteLLM

A realistic request can look like:

```text
                   Client
                     |
                     v
              POST /v1/chat/completions
                     |
                     v
             ┌───────────────┐
             │ Authentication│
             └───────┬───────┘
                     |
                     v
             ┌───────────────┐
             │ Rate Limiting │
             └───────┬───────┘
                     |
                     v
             ┌───────────────┐
             │ Budget Check  │
             └───────┬───────┘
                     |
                     v
             ┌───────────────┐
             │ Model Router  │
             └───────┬───────┘
                     |
             ┌───────┴────────┐
             ↓                ↓
         Deployment A      Deployment B
             |                |
             └───────┬────────┘
                     ↓
                LLM Provider
                     |
                     v
               Raw Response
                     |
                     v
            Response Transform
                     |
                     v
               Cost Tracking
                     |
                     v
                 Logging
                     |
                     v
                  Client
```

This is broadly consistent with LiteLLM's documented gateway architecture. ([GitHub][3])

---

# 26. Configuration

A gateway can be configured with a model list.

Conceptually:

```yaml
model_list:
  - model_name: fast-model
    litellm_params:
      model: provider/model-a
      api_key: ...

  - model_name: powerful-model
    litellm_params:
      model: provider/model-b
      api_key: ...
```

Then your application doesn't necessarily need to know the underlying provider deployment.

It can request:

```text
fast-model
```

and LiteLLM decides which actual deployment corresponds to it.

The official quick-start documentation uses this model-list/configuration approach for the Proxy Server. ([LiteLLM][1])

---

# 27. Why model aliases matter

This is a very useful architecture pattern.

Instead of your application hardcoding:

```text
gpt-specific-version
```

you could expose:

```text
production-fast
production-smart
production-cheap
```

Then:

```text
production-fast
        ↓
Provider A / Model X

production-smart
        ↓
Provider B / Model Y
```

Later, you can change the underlying model without modifying every application.

This gives you an abstraction:

```text
Application
     |
     ↓
logical model
     |
     ↓
LiteLLM
     |
     ↓
physical model/provider
```

---

# 28. Multi-provider strategy

Imagine your application requires high availability.

You could configure:

```text
                    smart-model
                         |
             ┌───────────┼───────────┐
             ↓           ↓           ↓
          OpenAI      Azure        Anthropic
```

Then:

```text
Normal traffic
      ↓
OpenAI

OpenAI unavailable
      ↓
Azure

Azure unavailable
      ↓
Anthropic
```

Your application doesn't have to implement all of this itself.

---

# 29. Where LiteLLM fits in an AI application

Suppose you're building an AI SaaS:

```text
                    ┌──────────────┐
                    │ React / Next │
                    └──────┬───────┘
                           |
                           v
                    ┌──────────────┐
                    │   Backend    │
                    │ Node / Go    │
                    └──────┬───────┘
                           |
                           v
                    ┌──────────────┐
                    │   LiteLLM    │
                    │   Gateway    │
                    └──────┬───────┘
                           |
              ┌────────────┼────────────┐
              ↓            ↓            ↓
           OpenAI       Anthropic     Gemini
```

Your backend focuses on:

```text
Business logic
Users
Authentication
RAG
Agents
Tools
Database
Billing
```

LiteLLM focuses on:

```text
LLM connectivity
Routing
Fallbacks
Provider abstraction
Cost
Usage
Rate limits
```

That separation is valuable.

---

# 30. Why LiteLLM is relevant to your Mistral Console project

This is where it becomes particularly relevant to what you've been exploring.

You were looking at building a **Mistral Console-like platform**.

A simplified architecture could be:

```text
                    YOUR CONSOLE
                         |
          ┌──────────────┼──────────────┐
          ↓              ↓              ↓
       Projects       API Keys       Usage
          |              |              |
          └──────────────┼──────────────┘
                         ↓
                  YOUR BACKEND
                         |
                         ↓
                  ┌─────────────┐
                  │   LiteLLM   │
                  │   Gateway   │
                  └──────┬──────┘
                         |
          ┌──────────────┼──────────────┐
          ↓              ↓              ↓
       Mistral         OpenAI        Anthropic
```

Your console becomes the **control plane/UI**, while LiteLLM can provide much of the **LLM data-plane/gateway functionality**.

---

# 31. Control plane vs data plane

This distinction is important if you're designing the architecture.

### Control plane

Manages:

```text
Users
Teams
Projects
API keys
Models
Budgets
Permissions
Configuration
Analytics
```

### Data plane

Handles:

```text
Actual LLM requests
Streaming
Routing
Retries
Provider communication
Responses
```

You could architect:

```text
                 YOUR CONSOLE
                 CONTROL PLANE
                      |
        ┌─────────────┼─────────────┐
        ↓             ↓             ↓
     Users         Projects       Keys
                      |
                      ↓
                Configuration
                      |
                      v
              ┌──────────────┐
              │   LiteLLM    │
              │    Proxy     │
              └──────┬───────┘
                     |
               DATA PLANE
                     |
        ┌────────────┼────────────┐
        ↓            ↓            ↓
     Mistral       OpenAI       Gemini
```

That is a strong architecture for an LLM platform.

---

# 32. What LiteLLM does NOT do

LiteLLM is not your complete AI application.

It doesn't replace:

```text
React
Next.js
PostgreSQL
Redis
LangGraph
RAG
Vector DB
Your business logic
```

For example, if you're building a chatbot:

```text
                 Your Application
                       |
          ┌────────────┼────────────┐
          ↓            ↓            ↓
       Auth          RAG          Agents
          |            |            |
          └────────────┼────────────┘
                       ↓
                   LiteLLM
                       |
                ┌──────┼──────┐
                ↓      ↓      ↓
              GPT   Claude  Gemini
```

LiteLLM primarily solves the **LLM access/gateway layer**.

---

# 33. The simplest way to remember it

Think of the stack like this:

```text
┌─────────────────────────────────────┐
│          Your AI Application        │
│                                     │
│ UI / Agents / RAG / Business Logic  │
└──────────────────┬──────────────────┘
                   │
                   ▼
┌─────────────────────────────────────┐
│              LiteLLM                │
│                                     │
│ Gateway / Routing / Auth / Cost     │
│ Rate Limits / Fallback / Logging    │
└──────────────────┬──────────────────┘
                   │
          ┌────────┼────────┐
          ▼        ▼        ▼
       OpenAI   Anthropic  Gemini
```

So the one-line definition is:

> **LiteLLM is an LLM abstraction and gateway layer that lets applications communicate with many LLM providers through a standardized interface while adding routing, fallbacks, authentication, rate limiting, cost tracking, logging, and other production controls.**

The official documentation is the best reference for its current provider/API support and deployment model: [LiteLLM Documentation](https://docs.litellm.ai/?utm_source=chatgpt.com) and [LiteLLM GitHub repository](https://github.com/BerriAI/litellm?utm_source=chatgpt.com). ([LiteLLM][1])

[1]: https://docs.litellm.ai/?utm_source=chatgpt.com "LiteLLM - Getting Started | liteLLM"
[2]: https://github.com/Arindam200/litellm-docs/blob/main/ARCHITECTURE.md?utm_source=chatgpt.com "litellm-docs/ARCHITECTURE.md at main · Arindam200/litellm-docs · GitHub"
[3]: https://github.com/BerriAI/litellm/blob/litellm_internal_staging/ARCHITECTURE.md?utm_source=chatgpt.com "litellm/ARCHITECTURE.md at litellm_internal_staging · BerriAI/litellm · GitHub"
[4]: https://github.com/sensuslab/litellm-base/blob/main/docs/my-website/docs/routing.md?utm_source=chatgpt.com "litellm-base/docs/my-website/docs/routing.md at main · sensuslab/litellm-base · GitHub"
