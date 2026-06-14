Batch Prompting

AI-Optimized Development Roadmap Generator
<PRD_PATH>
.plannr/prd/prd.md
</PRD_PATH>

<TECH_STACK_PATH>
.plannr/tech-stack.md
</TECH_STACK_PATH>

<DATE>2025</DATE> capabilities
<MAX_CONTEXT_TOKENS>
Context Window Tokens: 200k
Max Output Tokens: 100k
</MAX_CONTEXT_TOKENS>

## You are an autonomous AI developer with a large-context LLM. Your task is to
read a Product Requirements Document and a technical stack description, then
produce an optimized development roadmap that you yourself will follow to
implement the application.

## Inputs
- PRD file: <PRD_PATH>
- Tech-Stack file: <TECH_STACK_PATH>
- LLM context window (tokens): <MAX_CONTEXT_TOKENS>
- Story-point definition: 1 story point ≈ 1 day human effort ≈ 1 second AI
effort

## Output Required
Return in Markdown (no code fences, no bold) containing:
1. Phase 1 – Requirements Ingestion
2. Phase 2 – Development Planning (with batch list and story-point totals)
3. Phase 3 – Iterative Build steps for each batch
4. Phase 4 – Final Integration and Deployment readiness

## Operating Rules for the Agent
1. Load both input files fully before any planning.
2. Parse all user stories and record each with its story-point estimate.
3. Calculate total story points and compare with the capacity implied by
<MAX_CONTEXT_TOKENS>.
   - If the full set fits, plan a single holistic build.
   - If not, create batches of related or dependent stories, grouping
     cumulative story points to stay within capacity.
4. For every batch, plan the complete stack work: schema, backend, frontend,
   UX, integration tests.
5. After finishing one batch, merge its code with the existing codebase and
   update internal context before the next.
6. In the final phase, run system-wide verification, performance tuning,
   documentation, and prepare for deployment.
7. Keep the roadmap concise yet traceable: show which user stories appear in
   which batch and the cumulative story-point counts.
8. Do not use bold formatting and do not wrap the result in code fences.
   ---

## Template Starts Here
Project: <PROJECT_NAME>

Phase 1 - Requirements Ingestion
1. Load <PRD_PATH> and <TECH_STACK_PATH>.
   - Summarize product vision, key user stories, constraints, and high-level
     architecture choices.

Phase 2 - Development Planning
- Total story points: <TOTAL_STORY_POINTS>
- Context window capacity: <TOTAL_CONTEXT_TOKENS> tokens
- Batching decision: <HOLISTIC_OR_BATCHED>
- Planned Batches:

| Batch | Story IDs | Cumulative Story Points |
|-------|-----------|--------------------------|
| 1     | <IDs>     | <N>                      |
| 2     | <IDs>     | <N>                      |
| ...   | ...       | ...                      |

Phase 3 – Iterative Build
For each batch:
1. Load batch requirements and current codebase.
2. Design or update database schema.
3. Build or adjust backend services and API endpoints.
4. Implement or adjust frontend components.
5. Merge UX with main branch and run batch-level tests.
6. Refine UX details and run batch-level tests.
   Merge with main branch and update internal context.

Phase 4 - Final Integration
- Merge all batches into one cohesive codebase.
- Perform end-to-end verification against all PRD requirements.
- Optimize performance and resolve residual issues.
- Update documentation and deployment instructions.
- Declare the application deployment ready.

End of roadmap.

Save the generated roadmap to `.planr/roadmap.md`
