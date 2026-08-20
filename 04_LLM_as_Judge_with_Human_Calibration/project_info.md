# PROJECT 4 - LLM-as-Judge with Human Calibration (Evals)
Tools - Streamlit, Python, DeepEval, FastAPI, Claude API, Postgres, Docker.  

### Why this project signals 
Evaluation is the round candidates most often say they wish they had prepared for, and almost nobody has quantified whether their judge agrees with a human. Producing a kappa score and three measured bias numbers puts you ahead of engineers with more years of experience than you.

## PHASE 1 
### Write judge prompts against a real rubric
- Pick one task with real outputs. RAG answers from Project 1 work well and make your portfolio cohere.  
- Define three to five criteria, each on a three or five point ordinal scale with every point defined in words. A one to ten scale produces noise you will spend a week chasing.  
- Have the judge return structured output with its reasoning first and scores second. Reason before score measurably improves consistency, and you should measure it rather than assume it.
## PHASE 2 
### Hand label 200 outputs to build the gold standard
- Sample stratified across easy, hard, adversarial, and deliberately broken outputs. A calibration set with no failures has no variance and teaches the judge nothing.  
- Build a small Streamlit labeling interface showing input, output, and rubric, capturing a score per criterion plus a free text note. Store results in Postgres with labeler id and timestamp.  
- Label twenty of them twice on different days and compute your own self agreement. That number is your ceiling, because the judge cannot be more consistent than the humans defining correct.
## PHASE 3 
### Measure agreement, then close the gaps
- Compute weighted Cohen kappa for the ordinal scores and Spearman correlation alongside it. Report both.  
- Pull the twenty largest disagreements and read them one by one. In nearly every case the rubric is ambiguous rather than the model being wrong, which is the single most useful lesson in this project.  
- Sharpen the wording, add two or three anchor examples per score point, re run, and re measure. Track agreement across iterations and chart it. That improvement curve belongs in the README.
## PHASE 4 
### Test the judge for its known bises
- Position bias: run pairwise comparisons in both orders and measure how often the verdict flips. A flip rate above roughly ten percent means your pairwise setup is not trustworthy yet.  
- Length bias: hold quality constant and correlate score against output length. If longer wins, your rubric is rewarding volume.  
- Self preference: have one model family judge outputs from itself and a competitor, then swap the judge and compare verdicts on the same pairs.  
- Publish all three numbers. Most working engineers have never quantified any of them, which is precisely why it stands out in an interview.
## PHASE 5 
### Gate releases on calibrated scores
- Wire the judge into DeepEval and run it as a CI job against a fixed evaluation set on every pull request.  
- Set explicit thresholds: no criterion may drop more than a defined amount, and the safety criterion may not drop at all. Fail the build on regression.  
- Store every run in Postgres and chart scores over time in Streamlit, so quality has a trend line rather than an anecdote.  
- Demo it by opening a pull request that intentionally weakens a prompt and letting CI reject it on camera.
### Done when 
A pull request that degrades output quality fails CI automatically, and the README reports judge to human agreement plus three measured bias numbers.
### Resume line:  
Built an LLM as judge evaluation pipeline calibrated against N human labels at kappa X; quantified position, length, and self preference bias and gated releases on it in CI.
### Where this usually goes wrong  
- No human baseline at all, which makes every judge score unfalsifiable.  
- One to ten scales, which produce inconsistent scores across runs and labelers.  
- Judging outputs with the same model that produced them.  
- Tuning the rubric on the same examples you report agreement on, which is leakage.
### Stretch goals:  
Active learning to select the next most informative examples to label, score slicing by user cohort, and drift detection on sampled production traffic.