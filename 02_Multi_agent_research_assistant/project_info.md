# PROJECT 2 - Multi-Agent Research Assistant (Agents)
Tools - React js, Python, Tavily, LangGraph, Claude API, Redis, FastAPI, Docker.  

### Why this project signals 
Interviewers have seen hundreds of agent demos and almost none that survive a restart, cap their own spend, or explain what they did. The differentiator here is not the agents. It is durable state, budgets, and step level tracing, which are the three things a production agent has and a tutorial agent does not.

## PHASE 1 
### Build three specialists 
- Planner takes a research question and returns a structured plan of sub questions. Researcher executes one sub question with search and returns findings. Writer turns findings into a report with citations.  
- A specialist is a prompt plus a tool set plus an output schema. It is not a personality. Skip the you are a world class researcher framing and define Pydantic models for every hand off instead.  
- Test each agent alone before wiring them together. If the planner produces vague sub questions in isolation, no orchestration will rescue it.
## PHASE 2 
### Add a supervisor that routes and reviews 
- Model the system as a LangGraph state graph. Nodes are agents, edges are supervisor routing decisions, and the shared state object is the single source of truth.  
- After each researcher pass the supervisor checks the output against the plan: is this sub question answered, are sources missing, is another pass justified.  
- Enforce budgets in the graph rather than in prompts: maximum sub questions, maximum searches per sub question, maximum total tokens, and a wall clock ceiling. A prompt asking the model to be efficient is not a budget.  
- Allow the reviewer to send work back exactly once. Unlimited revision loops are how agent runs quietly cost twelve dollars.
## PHASE 3 
### Give the researcher live search with source tracking 
- Every finding is a record: claim, source URL, snippet, and retrieval timestamp. Findings without provenance are unusable in the writer step.
- Fetch and extract the page rather than trusting search snippets, which are truncated and often misleading.  
- Deduplicate by URL and cap results per domain so a single site cannot dominate a report.  
- Handle each failure path explicitly: no results, rate limited, paywalled, timed out. Each returns a structured status the supervisor can act on rather than an exception that kills the run.
## PHASE 4 
### Persist run state in Redis  
- Write graph state after every node: run id, plan, completed sub questions, findings so far, and cumulative token spend.  
- Now a crashed or redeployed process resumes instead of replaying, which is the difference between a demo and a service.  
- The same store gives you idempotency, since re entering a completed node returns the cached result, and it powers a status endpoint so callers can see progress.
## PHASE 5 
### Ship a report endpoint with citations and a trace 
- POST /research returns a run id immediately. GET /research/{id} returns status and then the finished report. Stream progress events so the interface is not a four minute spinner.  
- Every claim in the report carries a citation, and each citation is validated against a real finding record before the report is returned.  
- Expose GET /research/{id}/trace returning the full step log: which agent ran, what it received, what it produced, which tools it called, tokens, and latency per step.  
- That trace endpoint is what makes this project interview proof. When they ask how you would debug an agent that returned a bad answer, you open the trace instead of describing one.
### Done when 
A research question returns a fully cited report in under five minutes, a killed process resumes from where it stopped, and every run has a viewable step by step trace.
### Resume line:  
Built a multi agent research system with supervisor and worker topology, durable run state in Redis, per run cost caps, and step level tracing for debugging.
### Where this usually goes wrong  
- Agents defined by personality prompts instead of typed schemas, which makes hand offs unreliable.  
- No budget enforcement, so a single run silently costs more than the whole project.  
- Treating search failures as exceptions rather than states the supervisor can route around.  
- No trace, which means you cannot answer the one debugging question every interviewer asks.
### Stretch goals:  
Fan out researchers in parallel and fan in results, detect contradictions between sources, and add a human approval gate before the writer runs.