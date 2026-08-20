## DeepEval — in depth

**DeepEval** is an open-source **evaluation framework for LLM applications**. Think of it as **unit testing + benchmarking for AI systems**.

While **LiteLLM** helps you *call and manage LLMs*, **DeepEval** helps you determine whether the responses your LLM application produces are actually good.

### The simplest mental model

```text
LiteLLM
"How do I call and manage my LLMs?"

DeepEval
"How do I know whether my LLM application works correctly?"
```

---

# 1. Why DeepEval exists

Traditional software can have tests like:

```python
def test_addition():
    assert add(2, 3) == 5
```

For LLM applications, outputs aren't deterministic.

If you ask:

```text
Explain CAP theorem.
```

you might get:

```text
CAP theorem says a distributed system cannot simultaneously guarantee...
```

Another model might say:

```text
CAP describes the trade-off between consistency, availability...
```

Both could be correct.

So this doesn't work well:

```python
assert response == "exact expected text"
```

Instead, you need to evaluate qualities such as:

* Is the answer correct?
* Is it relevant?
* Is it grounded in retrieved documents?
* Did the model hallucinate?
* Did it follow the instructions?
* Was the context useful?
* Is the reasoning acceptable?
* Did an agent use the correct tool?
* Is the answer safe?

DeepEval provides metrics and testing infrastructure for this.

---

# 2. Where DeepEval fits

Suppose you're building a RAG chatbot:

```text
User
 ↓
Your Application
 ↓
Retriever
 ↓
Vector DB
 ↓
LLM
 ↓
Answer
```

DeepEval sits around this system:

```text
                 ┌───────────────┐
                 │ Your AI App   │
                 └───────┬───────┘
                         │
                         ▼
                    LLM Response
                         │
                         ▼
                 ┌───────────────┐
                 │   DeepEval    │
                 │               │
                 │ Correct?      │
                 │ Relevant?     │
                 │ Hallucinated? │
                 │ Grounded?     │
                 └───────────────┘
```

---

# 3. DeepEval vs normal testing

Traditional testing:

```text
Input
  ↓
Function
  ↓
Expected output
  ↓
assert actual == expected
```

LLM evaluation:

```text
Input
  ↓
LLM Application
  ↓
Generated output
  ↓
Evaluation metrics
  ↓
Score
```

For example:

```text
Question:
"What is CAP theorem?"

Answer:
"CAP theorem says..."
```

DeepEval might evaluate:

```text
Correctness      0.91
Relevance        0.96
Completeness     0.84
Hallucination    0.08
```

You can then define thresholds.

For example:

```text
Correctness >= 0.8
Relevance   >= 0.8
Hallucination <= 0.2
```

---

# 4. Core concept: LLMTestCase

DeepEval uses test cases to represent individual LLM interactions.

Conceptually:

```python
from deepeval.test_case import LLMTestCase

test_case = LLMTestCase(
    input="What is CAP theorem?",
    actual_output="CAP theorem describes..."
)
```

You can additionally provide things such as:

```text
expected_output
retrieval_context
context
tools_called
expected_tools
```

So the test case becomes the input to your evaluation metrics.

---

# 5. Example

Imagine you're testing a RAG system.

```python
test_case = LLMTestCase(
    input="What is CAP theorem?",
    actual_output="CAP theorem says...",
    retrieval_context=[
        "CAP theorem concerns consistency, availability, and partition tolerance."
    ]
)
```

Then you can evaluate:

```text
                    Test Case
                       |
        ┌──────────────┼──────────────┐
        ↓              ↓              ↓
     Answer        Retrieved       Question
                   Context
        |
        ▼
    DeepEval
        |
 ┌──────┼─────────┐
 ↓      ↓         ↓
Faithful Relevant Correct
```

---

# 6. LLM-as-a-Judge

One of DeepEval's important ideas is **LLM-as-a-judge**.

Instead of manually checking thousands of responses, another LLM evaluates the response.

For example:

```text
User question
      +
Generated answer
      +
Evaluation criteria
      |
      v
Evaluator LLM
      |
      v
Score + explanation
```

For example, an evaluator might be asked:

```text
Does the answer correctly explain CAP theorem
based on the provided context?
```

The evaluator returns something like:

```text
Score: 0.92

Reason:
The answer correctly identifies the three CAP properties
and explains the partition tolerance constraint.
```

This allows automated evaluation at scale.

---

# 7. Important DeepEval metrics

DeepEval provides a collection of metrics for different kinds of LLM applications.

Some important ones are:

### Answer Relevancy

Question:

> Is the response actually relevant to what the user asked?

Example:

```text
Question:
"What is Redis?"

Bad:
"Redis was created in 2009..."

Good:
"Redis is an in-memory data store..."
```

---

### Faithfulness

Especially important for RAG.

Question:

> Is the generated answer supported by the retrieved context?

Example:

```text
Retrieved context:
"Redis is an in-memory key-value store."

Answer:
"Redis is an in-memory key-value store."
```

High faithfulness.

But:

```text
Answer:
"Redis is an in-memory key-value store created by Microsoft."
```

The Microsoft claim isn't supported by the context.

Therefore:

```text
Faithfulness ↓
```

---

### Contextual Relevancy

Question:

> Did the retrieval system retrieve useful information?

Suppose the user asks:

```text
"What is Redis?"
```

Retriever returns:

```text
Redis documentation       ← useful
PostgreSQL documentation  ← irrelevant
Docker documentation      ← irrelevant
Kubernetes documentation  ← irrelevant
```

Contextual relevancy will detect that much of the retrieved context isn't useful.

---

### Contextual Recall

Question:

> Did retrieval retrieve the information necessary to answer the question?

This is important because a RAG system can fail **before the LLM even generates the answer**.

```text
Question
   ↓
Retriever
   ↓
Wrong documents
   ↓
LLM
   ↓
Bad answer
```

DeepEval can help identify that the retrieval stage is the problem.

---

# 8. RAG evaluation

This is probably one of DeepEval's most useful applications.

A RAG pipeline:

```text
             User Question
                   |
                   v
              Embedding
                   |
                   v
               Vector DB
                   |
                   v
           Retrieved Context
                   |
                   v
                  LLM
                   |
                   v
                Answer
```

DeepEval lets you evaluate multiple stages.

```text
             RAG Evaluation
                   |
       ┌───────────┼───────────┐
       ↓           ↓           ↓
 Retrieval      Generation    Overall
       |           |           |
       ↓           ↓           ↓
Recall         Faithfulness  Correctness
Relevancy      Relevancy     Relevancy
```

This is much more useful than simply asking:

> "Does my chatbot seem good?"

---

# 9. Hallucination detection

Suppose your RAG context says:

```text
Prateek's product uses PostgreSQL.
```

But the LLM responds:

```text
Prateek's product uses MongoDB.
```

DeepEval can evaluate whether the generated answer is supported by the available context.

Conceptually:

```text
Context
  |
  v
"Uses PostgreSQL"
  |
  v
Generated answer
  |
  v
"Uses MongoDB"
  |
  v
Evaluator
  |
  v
Unsupported claim
```

This is especially useful in:

* enterprise RAG
* customer support
* legal applications
* financial applications
* documentation assistants

---

# 10. LLM application testing

DeepEval integrates with Python testing workflows.

You can treat an LLM test similarly to a normal software test:

```text
                CI/CD
                  |
                  v
             DeepEval
                  |
        ┌─────────┼─────────┐
        ↓         ↓         ↓
       Test      Test      Test
        1         2         3
        ↓         ↓         ↓
      PASS      PASS      FAIL
```

For example:

```python
assert_test(
    test_case,
    [
        relevancy_metric,
        faithfulness_metric
    ]
)
```

Then your deployment pipeline can reject changes that significantly degrade evaluation scores.

---

# 11. Regression testing

This is extremely important.

Imagine you change your prompt.

### Version 1

```text
Prompt A
   ↓
Accuracy: 91%
```

You optimize it:

```text
Prompt B
   ↓
Accuracy: 84%
```

The application may still "look fine" during manual testing.

DeepEval gives you a way to catch this:

```text
                Prompt change
                     |
                     v
                  DeepEval
                     |
            ┌────────┴────────┐
            ↓                 ↓
       Previous score     New score
          91%                84%
            |                 |
            └────────┬────────┘
                     ↓
                  REGRESSION
```

This makes LLM development much closer to conventional software engineering.

---

# 12. Dataset-based evaluation

Testing one question isn't enough.

You could create:

```text
evaluation_dataset/
│
├── question_001
├── question_002
├── question_003
├── question_004
└── ...
```

For example:

```text
100 questions
    ↓
Your AI application
    ↓
100 responses
    ↓
DeepEval
    ↓
Metrics
```

Then you can compare different versions.

```text
                 Version A   Version B
Relevancy          0.89        0.94
Faithfulness       0.91        0.92
Correctness        0.86        0.90
```

Now you have measurable evidence that Version B is better.

---

# 13. Synthetic test generation

For large systems, manually creating thousands of evaluation cases is expensive.

DeepEval supports workflows around generating test cases from documents/data so you can construct evaluation datasets more efficiently.

Conceptually:

```text
Your Documents
      |
      v
Test Generation
      |
      v
Evaluation Dataset
      |
      v
Your RAG Application
      |
      v
DeepEval
```

This is useful when you have a large knowledge base.

---

# 14. Agent evaluation

DeepEval isn't limited to simple chatbots.

Suppose you have an AI agent:

```text
User
 ↓
Agent
 ├── Search Web
 ├── Query Database
 ├── Call API
 ├── Calculator
 └── LLM
 ↓
Final Answer
```

You may want to test:

```text
Did the agent:
✓ choose the correct tool?
✓ call the correct tool?
✓ provide correct arguments?
✓ call tools in the correct order?
✓ produce the correct final response?
```

DeepEval has metrics and tracing concepts intended for evaluating more complex LLM systems and agents.

---

# 15. Tool-call evaluation

Consider:

```text
User:
"What's the weather in Bangalore?"
```

Agent should:

```text
weather_tool(
    city="Bangalore"
)
```

But imagine it does:

```text
weather_tool(
    city="Mumbai"
)
```

The final response might still look plausible.

Tool-call evaluation can identify that the agent's behavior was incorrect.

So evaluation isn't limited to:

```text
Input → Output
```

It can also inspect:

```text
Input
 ↓
Agent
 ↓
Tool calls
 ↓
Intermediate steps
 ↓
Output
```

---

# 16. DeepEval tracing

For complex applications, you need to understand the execution path.

Example:

```text
User
 ↓
Agent
 ↓
Retriever
 ↓
LLM
 ↓
Tool
 ↓
LLM
 ↓
Final answer
```

Tracing lets you reason about the individual components rather than treating the whole system as a black box.

This is especially useful for:

* agents
* multi-step workflows
* RAG
* tool calling
* complex chains

---

# 17. DeepEval + LangChain

You can use DeepEval with LLM application frameworks such as LangChain.

Architecture:

```text
             LangChain
                 |
       ┌─────────┼─────────┐
       ↓         ↓         ↓
    Retriever   Agent      LLM
       |         |         |
       └─────────┼─────────┘
                 ↓
              DeepEval
```

LangChain handles application orchestration.

DeepEval handles evaluation.

---

# 18. DeepEval + LiteLLM

This combination is particularly interesting.

They solve different problems.

```text
                 Your AI Platform
                       |
             ┌─────────┴─────────┐
             ↓                   ↓
          LiteLLM             DeepEval
             |                   |
       LLM infrastructure     Evaluation
             |                   |
      ┌──────┼──────┐       ┌────┼────┐
      ↓      ↓      ↓       ↓    ↓    ↓
    GPT    Claude Gemini   RAG  Agent Quality
```

### LiteLLM

Handles:

```text
Model access
Provider abstraction
Routing
Fallback
Rate limits
API keys
Cost
```

### DeepEval

Handles:

```text
Quality
Correctness
Relevancy
Faithfulness
Hallucination
Regression testing
Agent evaluation
RAG evaluation
```

Together:

```text
                    AI Application
                         |
                         v
                    LiteLLM
                         |
                 Model providers
                         |
                         v
                    Response
                         |
                         v
                    DeepEval
                         |
                 Quality metrics
```

---

# 19. DeepEval vs LangSmith

These tools overlap somewhat but have different emphasis.

### DeepEval

Strong focus on:

```text
Evaluation
Testing
Metrics
CI/CD
Regression testing
RAG evaluation
LLM testing
```

### LangSmith

Strong focus on:

```text
Tracing
Observability
Debugging
Datasets
Evaluation
LangChain ecosystem
```

A simplified distinction:

```text
DeepEval
    ↓
"Is my AI system good?"

LangSmith
    ↓
"What happened inside my AI system?"
```

In practice, there is overlap.

---

# 20. DeepEval vs RAGAS

Another important comparison.

### RAGAS

Primarily known for evaluating **RAG pipelines**.

```text
RAG
 ↓
RAGAS
```

### DeepEval

Broader:

```text
                 DeepEval
                    |
       ┌────────────┼─────────────┐
       ↓            ↓             ↓
      RAG          Agents       Chatbots
       ↓            ↓             ↓
   Evaluation   Evaluation   Evaluation
```

So if you're building only a RAG system, RAGAS can be sufficient.

If you're building a broader AI platform, DeepEval gives you a wider testing framework.

---

# 21. DeepEval vs traditional unit tests

They should **not replace each other**.

Use normal unit tests for deterministic logic:

```text
Database functions
Authentication
API validation
Business logic
Calculations
```

Use DeepEval for probabilistic AI behavior:

```text
LLM output
RAG quality
Agent behavior
Tool selection
Hallucination
Instruction following
```

A production AI application should ideally have both.

```text
                 Test Suite
                     |
          ┌──────────┴──────────┐
          ↓                     ↓
   Traditional Tests        DeepEval
          |                     |
      Software             AI behavior
      correctness           quality
```

---

# 22. Example production pipeline

Suppose you're building an AI customer-support system.

```text
                    User
                     |
                     v
                 Frontend
                     |
                     v
                  Backend
                     |
                     v
                   RAG
                     |
                     v
                  LiteLLM
                     |
          ┌──────────┼──────────┐
          ↓          ↓          ↓
        GPT       Claude      Gemini
          |
          v
       Response
          |
          v
       DeepEval
          |
    ┌─────┼──────┐
    ↓     ↓      ↓
Faithful Relevant Correct
    |
    v
Quality threshold
    |
 ┌──┴──┐
 ↓     ↓
PASS  FAIL
```

---

# 23. CI/CD integration

This is where DeepEval becomes much more valuable than a simple evaluation script.

Imagine you have:

```text
GitHub
   |
   v
Pull Request
   |
   v
Tests
   |
   ├── Unit tests
   ├── Integration tests
   └── DeepEval
           |
           ├── Faithfulness
           ├── Relevancy
           └── Correctness
   |
   v
Deployment
```

Suppose a developer changes your RAG prompt.

DeepEval runs:

```text
500 evaluation cases
```

and discovers:

```text
Before:
Faithfulness = 94%

After:
Faithfulness = 79%
```

The PR can be rejected.

This gives you **evaluation-driven development** for LLM systems.

---

# 24. The key concept: threshold-based evaluation

Instead of simply getting:

```text
score = 0.83
```

you can establish a quality requirement:

```text
minimum_score = 0.80
```

Then:

```text
0.92 → PASS
0.87 → PASS
0.81 → PASS
0.79 → FAIL
```

This makes subjective LLM quality measurable enough to incorporate into engineering workflows.

---

# 25. A complete mental model

If you're building a serious AI platform, think about these layers:

```text
┌─────────────────────────────────────────────┐
│                  UI                         │
│          React / Next.js                   │
└──────────────────────┬──────────────────────┘
                       ↓
┌─────────────────────────────────────────────┐
│              Application                    │
│        Agents / RAG / Business Logic       │
└──────────────────────┬──────────────────────┘
                       ↓
┌─────────────────────────────────────────────┐
│                 LiteLLM                     │
│       Gateway / Routing / Cost / Keys      │
└──────────────────────┬──────────────────────┘
                       ↓
┌─────────────────────────────────────────────┐
│             LLM Providers                   │
│      OpenAI / Anthropic / Mistral / etc.   │
└──────────────────────┬──────────────────────┘
                       ↓
┌─────────────────────────────────────────────┐
│                DeepEval                     │
│ Evaluation / Testing / Quality / Metrics   │
└─────────────────────────────────────────────┘
```

Although DeepEval typically evaluates the application rather than literally sitting in the runtime request path, this is the right **conceptual architecture**.

---

# 26. LiteLLM + DeepEval in one sentence

Remember this:

> **LiteLLM manages how your application talks to LLMs; DeepEval measures how well your application performs with those LLMs.**

Or even shorter:

```text
LiteLLM  →  LLM infrastructure
DeepEval →  LLM quality
```

For the **Mistral Console-style platform you're considering**, I'd think of the architecture as:

```text
                         AI CONSOLE
                             |
              ┌──────────────┼──────────────┐
              ↓              ↓              ↓
          Projects         API Keys       Analytics
              |
              v
        ┌──────────────┐
        │   Backend    │
        └──────┬───────┘
               |
               v
        ┌──────────────┐
        │   LiteLLM    │
        │    Proxy     │
        └──────┬───────┘
               |
       ┌───────┼────────┐
       ↓       ↓        ↓
    Mistral  OpenAI  Anthropic
               |
               v
        ┌──────────────┐
        │   DeepEval   │
        └──────┬───────┘
               |
       ┌───────┼──────────┐
       ↓       ↓          ↓
    Quality  RAG       Agent
    Metrics  Metrics   Metrics
```

That combination gives you **LLM access + LLM governance + LLM evaluation**, which are three separate concerns that are often mistakenly put into one backend.
