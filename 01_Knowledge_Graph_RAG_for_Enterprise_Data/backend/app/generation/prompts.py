"""Prompts for answering, plus the retry prompt used when citations fail."""

ANSWER_PROMPT = """Answer the question using ONLY the numbered context below.

Rules:
- Every sentence stating a fact MUST end with a citation like [1] or [2][3].
- The number must match a context entry you actually used.
- An answer with no citations is invalid.
- If the context does not answer the question, reply exactly:
  INSUFFICIENT_CONTEXT
- Do not use knowledge from outside the context.
- Be concise. Three sentences at most.

Worked example.
Context:
[1] Jensen Huang is the CEO of NVIDIA.
[2] NVIDIA develops the H100.
Question: Who leads NVIDIA and what do they make?
Answer: Jensen Huang is NVIDIA's chief executive [1]. The company
develops the H100 [2].

Now the real one.

{context}

QUESTION: {question}

ANSWER:"""


# Used when an answer cited entries that were never retrieved, or cited
# nothing at all. Both are the same failure: a claim we cannot check.
REPAIR_PROMPT = """Your previous answer has a citation problem: {problem}

Valid citation numbers are: {valid}

Rewrite the answer so that every factual sentence ends with a valid
citation number in square brackets. Use only the numbers listed above.
If the context does not support an answer, reply exactly
INSUFFICIENT_CONTEXT.

{context}

QUESTION: {question}

PREVIOUS ANSWER: {answer}

CORRECTED ANSWER:"""


REFUSAL = (
    "I could not find enough information in the indexed documents to "
    "answer that."
)


INSUFFICIENT = "INSUFFICIENT_CONTEXT"
