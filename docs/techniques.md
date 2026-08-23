# Prompt technique catalogue

Prompt Playoff ships the following 61 versioned technique definitions. The catalogue is generated
from the YAML registry; the application still benchmarks candidates on your model and data before
you should treat a ranking as evidence.

| Technique | Family | Calls | Evidence |
|---|---|---:|---|
| [Maieutic prompting](#maieutic-prompting) | abductive-consistency | 2+ | documented |
| [Step-back prompting](#step-back-prompting) | abstraction | 2+ | documented |
| [Instance-adaptive zero-shot CoT](#instance-adaptive-zero-shot-cot) | adaptive-reasoning | 1+ | documented |
| [Graph of thoughts](#graph-of-thoughts) | aggregation | 2+ | documented |
| [Progressive-hint prompting](#progressive-hint-prompting) | answer-convergence | 2+ | documented |
| [Thread of thought (ThoT)](#thread-of-thought-thot) | chaotic-context | 1+ | documented |
| [Label definitions with boundary examples](#label-definitions-with-boundary-examples) | classification-control | 1+ | heuristic |
| [Code prompting](#code-prompting) | code-representation | 1+ | documented |
| [Chain of code](#chain-of-code) | code-simulation | 1+ | documented |
| [Program of thought](#program-of-thought) | computation | 2+ | documented |
| [Layer of thoughts (LoT)](#layer-of-thoughts-lot) | constraint-filtering | 1+ | documented |
| [Long-context map-reduce](#long-context-map-reduce) | context-management | 2+ | heuristic |
| [Creative constraint lattice](#creative-constraint-lattice) | creative-control | 1+ | heuristic |
| [Least-to-most prompting](#least-to-most-prompting) | decomposition | 2+ | documented |
| [Task decomposition](#task-decomposition) | decomposition | 2+ | benchmarked |
| [Chain of density](#chain-of-density) | densification | 2+ | documented |
| [Direct prompting with explicit constraints](#direct-prompting-with-explicit-constraints) | direct | 1+ | documented |
| [Chain of knowledge](#chain-of-knowledge) | dynamic-grounding | 2+ | documented |
| [Reflexion](#reflexion) | episodic-reflection | 2+ | documented |
| [Meta-prompting](#meta-prompting) | expert-delegation | 2+ | documented |
| [Contrastive chain of thought](#contrastive-chain-of-thought) | few-shot | 1+ | documented |
| [Few-shot schema with repair](#few-shot-schema-with-repair) | few-shot | 2+ | benchmarked |
| [Logic of thought](#logic-of-thought) | formal-logic | 1+ | documented |
| [Graph flattening](#graph-flattening) | graph-linearization | 1+ | documented |
| [Chain of note](#chain-of-note) | grounding | 1+ | documented |
| [Evidence-first grounded answer](#evidence-first-grounded-answer) | grounding | 1+ | heuristic |
| [Directional stimulus prompting](#directional-stimulus-prompting) | hint-conditioning | 2+ | documented |
| [Cumulative reasoning](#cumulative-reasoning) | incremental-proof | 2+ | documented |
| [Re-reading (RE2)](#re-reading-re2) | input-processing | 1+ | documented |
| [Rephrase and respond (RaR)](#rephrase-and-respond-rar) | input-processing | 1+ | documented |
| [System 2 attention (S2A)](#system-2-attention-s2a) | input-processing | 2+ | documented |
| [Scratchpad prompting](#scratchpad-prompting) | intermediate-computation | 1+ | documented |
| [Generated knowledge prompting](#generated-knowledge-prompting) | knowledge-elicitation | 2+ | documented |
| [Recitation-augmented prompting](#recitation-augmented-prompting) | memory-recitation | 1+ | documented |
| [Emotional stimuli prompting](#emotional-stimuli-prompting) | motivational-framing | 1+ | documented |
| [Role prompting](#role-prompting) | persona | 1+ | documented |
| [SimToM (simulated theory of mind)](#simtom-simulated-theory-of-mind) | perspective-taking | 2+ | documented |
| [Plan and execute](#plan-and-execute) | planning | 2+ | benchmarked |
| [Structured chain of thought](#structured-chain-of-thought) | program-structure | 1+ | documented |
| [Self-ask](#self-ask) | question-decomposition | 1+ | documented |
| [Verify and edit](#verify-and-edit) | rationale-repair | 2+ | documented |
| [Self-consistency sampling](#self-consistency-sampling) | sampling | 3+ | benchmarked |
| [Tree of thoughts](#tree-of-thoughts) | search | 6+ | documented |
| [Analogical prompting](#analogical-prompting) | self-generated-exemplars | 1+ | documented |
| [Metacognitive prompting](#metacognitive-prompting) | self-reflection | 1+ | documented |
| [Critique and revise](#critique-and-revise) | self-review | 2+ | benchmarked |
| [Backward verification](#backward-verification) | self-verification | 2+ | documented |
| [Chain of verification (CoVe)](#chain-of-verification-cove) | self-verification | 3+ | documented |
| [Skeleton of thought](#skeleton-of-thought) | structure-first | 2+ | documented |
| [Schema-first output](#schema-first-output) | structured-output | 1+ | heuristic |
| [Chain of symbol](#chain-of-symbol) | symbolic-representation | 1+ | documented |
| [Faithful chain of thought](#faithful-chain-of-thought) | symbolic-translation | 2+ | documented |
| [Tabular chain of thought](#tabular-chain-of-thought) | tabular-reasoning | 1+ | documented |
| [Chain of table](#chain-of-table) | tabular-transform | 1+ | documented |
| [Buffer of thoughts](#buffer-of-thoughts) | template-reuse | 2+ | documented |
| [Narrative of thought](#narrative-of-thought) | temporal-reasoning | 1+ | documented |
| [Chain of draft](#chain-of-draft) | thought-generation | 1+ | documented |
| [Zero-shot chain of thought](#zero-shot-chain-of-thought) | thought-generation | 2+ | documented |
| [ReAct tool loop](#react-tool-loop) | tool-use | 2+ | benchmarked |
| [Glossary-constrained translation](#glossary-constrained-translation) | translation-control | 1+ | heuristic |
| [Tests-first implementation](#tests-first-implementation) | verification | 2+ | heuristic |

## Technique cards

### Maieutic prompting

ID: <code>reasoning.maieutic</code> · Version: <code>1.0.0</code> · Family: <code>abductive-consistency</code>

Argue the claim true and argue it false, then settle it on which set of explanations holds together.

**Strong tasks:** classification, research.  
**Acceptable tasks:** structured_extraction.  
**Minimum calls:** 2; tools not required; evidence documented.

Source: [Maieutic Prompting: Logically Consistent Reasoning with Recursive Explanations](https://arxiv.org/abs/2205.11822), 2022.

### Step-back prompting

ID: <code>reasoning.step-back</code> · Version: <code>1.0.0</code> · Family: <code>abstraction</code>

Ask a general question about the principles involved, then answer the specific one with that context in hand.

**Strong tasks:** research, classification.  
**Acceptable tasks:** coding, structured_extraction, summarization.  
**Minimum calls:** 2; tools not required; evidence documented.

Source: [Take a Step Back: Evoking Reasoning via Abstraction in Large Language Models](https://arxiv.org/abs/2310.06117), 2023.

### Instance-adaptive zero-shot CoT

ID: <code>reasoning.instance-adaptive-cot</code> · Version: <code>1.0.0</code> · Family: <code>adaptive-reasoning</code>

Judge what this particular instance needs before reasoning, and spend steps only where the instance warrants them.

**Strong tasks:** classification, coding.  
**Acceptable tasks:** research, structured_extraction.  
**Minimum calls:** 1; tools not required; evidence documented.

Source: [Instance-adaptive Zero-shot Chain-of-Thought Prompting](https://arxiv.org/abs/2409.03460), 2024.

### Graph of thoughts

ID: <code>reasoning.graph-of-thought</code> · Version: <code>1.0.0</code> · Family: <code>aggregation</code>

Develop several partial solutions independently, then merge the parts that hold instead of picking one branch whole.

**Strong tasks:** research, creative_writing.  
**Acceptable tasks:** coding, summarization.  
**Minimum calls:** 2; tools not required; evidence documented.

Source: [Graph of Thoughts: Solving Elaborate Problems with Large Language Models](https://arxiv.org/abs/2308.09687), 2023.

### Progressive-hint prompting

ID: <code>reasoning.progressive-hint</code> · Version: <code>1.0.0</code> · Family: <code>answer-convergence</code>

Answer once, then answer again with the first answer supplied as a hint, and keep only what survives the second pass.

**Strong tasks:** coding, research.  
**Acceptable tasks:** classification, structured_extraction.  
**Minimum calls:** 2; tools not required; evidence documented.

Source: [Progressive-Hint Prompting Improves Reasoning in Large Language Models](https://arxiv.org/abs/2304.09797), 2023.

### Thread of thought (ThoT)

ID: <code>context.thread-of-thought</code> · Version: <code>1.0.0</code> · Family: <code>chaotic-context</code>

Walk a disordered context in manageable parts, summarising and judging the relevance of each before answering from what survived.

**Strong tasks:** research, summarization.  
**Acceptable tasks:** structured_extraction, classification.  
**Minimum calls:** 1; tools not required; evidence documented.

Source: [Thread of Thought Unraveling Chaotic Contexts](https://arxiv.org/abs/2311.08734), 2023.

### Label definitions with boundary examples

ID: <code>classification.label-rules</code> · Version: <code>1.0.0</code> · Family: <code>classification-control</code>

Define labels, decision boundaries, and positive and negative examples.

**Strong tasks:** classification.  
**Acceptable tasks:** structured_extraction.  
**Minimum calls:** 1; tools not required; evidence heuristic.

### Code prompting

ID: <code>reasoning.code-prompting</code> · Version: <code>1.0.0</code> · Family: <code>code-representation</code>

Rewrite the natural-language problem as pseudo-code with its conditions made explicit, then reason over that — without running anything.

**Strong tasks:** research, classification.  
**Acceptable tasks:** structured_extraction, coding.  
**Minimum calls:** 1; tools not required; evidence documented.

Source: [Code Prompting Elicits Conditional Reasoning Abilities in Text+Code LLMs](https://arxiv.org/abs/2401.10065), 2024.

### Chain of code

ID: <code>coding.chain-of-code</code> · Version: <code>1.0.0</code> · Family: <code>code-simulation</code>

Write the solution as code, run the parts that are computable, and simulate the parts that are not — stating each simulated result as a value.

**Strong tasks:** coding, research.  
**Acceptable tasks:** structured_extraction, classification.  
**Minimum calls:** 1; tools not required; evidence documented.

Source: [Chain of Code: Reasoning with a Language Model-Augmented Code Emulator](https://arxiv.org/abs/2312.04474), 2023.

### Program of thought

ID: <code>reasoning.program-of-thought</code> · Version: <code>1.0.0</code> · Family: <code>computation</code>

The model writes a program that computes the answer; the program runs in a restricted interpreter and the model answers from its output.

**Strong tasks:** coding.  
**Acceptable tasks:** structured_extraction, classification, research.  
**Minimum calls:** 2; tools not required; evidence documented.

Source: [Program of Thoughts Prompting: Disentangling Computation from Reasoning](https://arxiv.org/abs/2211.12588), 2022.

### Layer of thoughts (LoT)

ID: <code>reasoning.layer-of-thought</code> · Version: <code>1.0.0</code> · Family: <code>constraint-filtering</code>

Apply the constraints one layer at a time, each narrowing the candidates the previous layer left, so every exclusion has a named reason.

**Strong tasks:** research, classification.  
**Acceptable tasks:** structured_extraction, summarization.  
**Minimum calls:** 1; tools not required; evidence documented.

Source: [Layer-of-Thoughts Prompting (LoT): Leveraging LLM-Based Retrieval with Constraint Hierarchies](https://arxiv.org/abs/2405.11534), 2024.

### Long-context map-reduce

ID: <code>context.map-reduce</code> · Version: <code>1.0.0</code> · Family: <code>context-management</code>

Process bounded chunks independently, retain structured intermediate state, and reduce globally.

**Strong tasks:** summarization, research, translation, structured_extraction.  
**Acceptable tasks:** coding.  
**Minimum calls:** 2; tools not required; evidence heuristic.

### Creative constraint lattice

ID: <code>creative.constraint-lattice</code> · Version: <code>1.0.0</code> · Family: <code>creative-control</code>

Organize premise, audience, voice, exclusions, and structural beats without overconstraining prose.

**Strong tasks:** creative_writing.  
**Acceptable tasks:** translation, summarization.  
**Minimum calls:** 1; tools not required; evidence heuristic.

### Least-to-most prompting

ID: <code>reasoning.least-to-most</code> · Version: <code>1.0.0</code> · Family: <code>decomposition</code>

List the subproblems from simplest to hardest, then solve them in that order, each answer feeding the next.

**Strong tasks:** coding, research.  
**Acceptable tasks:** structured_extraction, summarization.  
**Minimum calls:** 2; tools not required; evidence documented.

Source: [Least-to-Most Prompting Enables Complex Reasoning in Large Language Models](https://arxiv.org/abs/2205.10625), 2022.

### Task decomposition

ID: <code>reasoning.decomposition</code> · Version: <code>1.0.0</code> · Family: <code>decomposition</code>

Split a complex task into explicit subproblems and combine verified partial results.

**Strong tasks:** coding, research, agents.  
**Acceptable tasks:** structured_extraction, summarization, translation.  
**Minimum calls:** 2; tools not required; evidence benchmarked.

Source: [Least-to-Most Prompting Enables Complex Reasoning in Large Language Models](https://arxiv.org/abs/2205.10625), 2022.

### Chain of density

ID: <code>summarization.chain-of-density</code> · Version: <code>1.0.0</code> · Family: <code>densification</code>

Write a deliberately sparse summary, then rewrite it at the same length with the salient entities it missed folded in.

**Strong tasks:** summarization.  
**Acceptable tasks:** research.  
**Minimum calls:** 2; tools not required; evidence documented.

Source: [From Sparse to Dense: GPT-4 Summarization with Chain of Density Prompting](https://arxiv.org/abs/2309.04269), 2023.

### Direct prompting with explicit constraints

ID: <code>direct.explicit-constraints</code> · Version: <code>1.0.0</code> · Family: <code>direct</code>

A concise instruction, explicit constraints, and a clear output contract.

**Strong tasks:** classification, summarization, translation.  
**Acceptable tasks:** structured_extraction, coding, creative_writing.  
**Minimum calls:** 1; tools not required; evidence documented.

Source: [Language Models are Few-Shot Learners](https://arxiv.org/abs/2005.14165), 2020.

### Chain of knowledge

ID: <code>grounding.chain-of-knowledge</code> · Version: <code>1.0.0</code> · Family: <code>dynamic-grounding</code>

Name the knowledge domains the question spans, draw the evidence from each separately, then reconcile them before answering.

**Strong tasks:** research.  
**Acceptable tasks:** classification, summarization.  
**Minimum calls:** 2; tools not required; evidence documented.

Source: [Chain-of-Knowledge: Grounding Large Language Models via Dynamic Knowledge Adapting over Heterogeneous Sources](https://arxiv.org/abs/2305.13269), 2023.

### Reflexion

ID: <code>verification.reflexion</code> · Version: <code>1.0.0</code> · Family: <code>episodic-reflection</code>

Attempt the task, write a verbal post-mortem naming what went wrong and what to do differently, then attempt it again with that note in hand.

**Strong tasks:** coding, agents.  
**Acceptable tasks:** research, structured_extraction.  
**Minimum calls:** 2; tools not required; evidence documented.

Source: [Reflexion: Language Agents with Verbal Reinforcement Learning](https://arxiv.org/abs/2303.11366), 2023.

### Meta-prompting

ID: <code>agents.meta-prompting</code> · Version: <code>1.0.0</code> · Family: <code>expert-delegation</code>

Act as a conductor that assigns each part of the task to a named specialist, then integrates their answers and resolves the disagreements.

**Strong tasks:** research, agents.  
**Acceptable tasks:** coding, creative_writing.  
**Minimum calls:** 2; tools not required; evidence documented.

Source: [Meta-Prompting: Enhancing Language Models with Task-Agnostic Scaffolding](https://arxiv.org/abs/2401.12954), 2024.

### Contrastive chain of thought

ID: <code>few-shot.contrastive-cot</code> · Version: <code>1.0.0</code> · Family: <code>few-shot</code>

Show both a correct and an incorrect worked example, so the model learns the boundary rather than only the target. Needs demonstrations.

**Strong tasks:** classification, structured_extraction.  
**Acceptable tasks:** coding, research.  
**Minimum calls:** 1; tools not required; evidence documented.

Source: [Contrastive Chain-of-Thought Prompting](https://arxiv.org/abs/2311.09277), 2023.

### Few-shot schema with repair

ID: <code>structured.few-shot-repair</code> · Version: <code>1.0.0</code> · Family: <code>few-shot</code>

Demonstrate valid outputs, parse the response, and repair one invalid generation.

**Strong tasks:** structured_extraction, classification.  
**Acceptable tasks:** translation.  
**Minimum calls:** 2; tools not required; evidence benchmarked.

Source: [Language Models are Few-Shot Learners](https://arxiv.org/abs/2005.14165), 2020.

### Logic of thought

ID: <code>reasoning.logic-of-thought</code> · Version: <code>1.0.0</code> · Family: <code>formal-logic</code>

Extract the propositions and their connectives, expand them under logical rules, and put the derived facts back into the prompt before answering.

**Strong tasks:** research, classification.  
**Acceptable tasks:** structured_extraction, coding.  
**Minimum calls:** 1; tools not required; evidence documented.

Source: [Logic-of-Thought: Injecting Logic into Contexts for Full Reasoning in Large Language Models](https://arxiv.org/abs/2409.17539), 2024.

### Graph flattening

ID: <code>reasoning.graph-flattening</code> · Version: <code>1.0.0</code> · Family: <code>graph-linearization</code>

Turn graph-shaped input into an ordered text form the model can read straight through, then reason over that form.

**Strong tasks:** structured_extraction, research.  
**Acceptable tasks:** coding, summarization.  
**Minimum calls:** 1; tools not required; evidence documented.

Source: [End-to-End Graph Flattening Method for Large Language Models](https://arxiv.org/abs/2402.13085), 2024.

### Chain of note

ID: <code>grounding.chain-of-note</code> · Version: <code>1.0.0</code> · Family: <code>grounding</code>

Write a reading note for each supplied source before answering, so an irrelevant source is rejected explicitly rather than quietly absorbed (arXiv 2311.09210).

**Strong tasks:** research.  
**Acceptable tasks:** summarization, structured_extraction.  
**Minimum calls:** 1; tools not required; evidence documented.

Source: [Chain-of-Note: Enhancing Robustness in Retrieval-Augmented Language Models](https://arxiv.org/abs/2311.09210), 2023.

### Evidence-first grounded answer

ID: <code>grounding.evidence-first</code> · Version: <code>1.0.0</code> · Family: <code>grounding</code>

Collect evidence first, map claims to sources, and answer only from supported material.

**Strong tasks:** research, summarization.  
**Acceptable tasks:** coding, agents.  
**Minimum calls:** 1; tools not required; evidence heuristic.

### Directional stimulus prompting

ID: <code>direct.directional-stimulus</code> · Version: <code>1.0.0</code> · Family: <code>hint-conditioning</code>

Extract the keywords the answer must be built around, then generate conditioned on those rather than on the input at large.

**Strong tasks:** summarization, creative_writing.  
**Acceptable tasks:** translation, research.  
**Minimum calls:** 2; tools not required; evidence documented.

Source: [Guiding Large Language Models via Directional Stimulus Prompting](https://arxiv.org/abs/2302.11520), 2023.

### Cumulative reasoning

ID: <code>reasoning.cumulative</code> · Version: <code>1.0.0</code> · Family: <code>incremental-proof</code>

Propose one candidate proposition at a time, verify it against what is already established, and keep only what passes.

**Strong tasks:** research, coding.  
**Acceptable tasks:** classification, structured_extraction.  
**Minimum calls:** 2; tools not required; evidence documented.

Source: [Cumulative Reasoning with Large Language Models](https://arxiv.org/abs/2308.04371), 2023.

### Re-reading (RE2)

ID: <code>reasoning.re-reading</code> · Version: <code>1.0.0</code> · Family: <code>input-processing</code>

Present the input twice and instruct the model to read it again before answering. One extra sentence, one call, no reasoning trace.

**Strong tasks:** structured_extraction, classification.  
**Acceptable tasks:** summarization, translation, research.  
**Minimum calls:** 1; tools not required; evidence documented.

Source: [Re-Reading Improves Reasoning in Large Language Models](https://arxiv.org/abs/2309.06275), 2023.

### Rephrase and respond (RaR)

ID: <code>reasoning.rephrase-and-respond</code> · Version: <code>1.0.0</code> · Family: <code>input-processing</code>

Restate the task in the model's own words, expanding what is implicit, then answer the restated version.

**Strong tasks:** classification, research.  
**Acceptable tasks:** structured_extraction, summarization, coding.  
**Minimum calls:** 1; tools not required; evidence documented.

Source: [Rephrase and Respond: Let Large Language Models Ask Better Questions for Themselves](https://arxiv.org/abs/2311.04205), 2023.

### System 2 attention (S2A)

ID: <code>reasoning.system2-attention</code> · Version: <code>1.0.0</code> · Family: <code>input-processing</code>

Strip the input down to what actually bears on the task, then solve using only the stripped version. Aimed at inputs carrying distractors.

**Strong tasks:** research, summarization.  
**Acceptable tasks:** structured_extraction, classification.  
**Minimum calls:** 2; tools not required; evidence documented.

Source: [System 2 Attention (is something you might need too)](https://arxiv.org/abs/2311.11829), 2023.

### Scratchpad prompting

ID: <code>reasoning.scratchpad</code> · Version: <code>1.0.0</code> · Family: <code>intermediate-computation</code>

Give the model an explicit workspace to hold intermediate state, and require the state to be rewritten in full after every step.

**Strong tasks:** coding, structured_extraction.  
**Acceptable tasks:** research, classification.  
**Minimum calls:** 1; tools not required; evidence documented.

Source: [Show Your Work: Scratchpads for Intermediate Computation with Language Models](https://arxiv.org/abs/2112.00114), 2021.

### Generated knowledge prompting

ID: <code>grounding.generated-knowledge</code> · Version: <code>1.0.0</code> · Family: <code>knowledge-elicitation</code>

Write out the facts the question depends on first, then answer from those statements rather than from the question directly.

**Strong tasks:** research, classification.  
**Acceptable tasks:** summarization, structured_extraction.  
**Minimum calls:** 2; tools not required; evidence documented.

Source: [Generated Knowledge Prompting for Commonsense Reasoning](https://arxiv.org/abs/2110.08387), 2021.

### Recitation-augmented prompting

ID: <code>grounding.recitation</code> · Version: <code>1.0.0</code> · Family: <code>memory-recitation</code>

Recite the passage the answer depends on from memory before answering, so the answer is read off something stated rather than produced directly.

**Strong tasks:** research.  
**Acceptable tasks:** classification, summarization, structured_extraction.  
**Minimum calls:** 1; tools not required; evidence documented.

Source: [Recitation-Augmented Language Models](https://arxiv.org/abs/2210.01296), 2022.

### Emotional stimuli prompting

ID: <code>direct.emotional-stimuli</code> · Version: <code>1.0.0</code> · Family: <code>motivational-framing</code>

Append a short statement of why the answer matters, which measurably shifts effort without changing the task.

**Strong tasks:** creative_writing, summarization.  
**Acceptable tasks:** research, classification, translation.  
**Minimum calls:** 1; tools not required; evidence documented.

Source: [Large Language Models Understand and Can Be Enhanced by Emotional Stimuli](https://arxiv.org/abs/2307.11760), 2023.

### Role prompting

ID: <code>direct.role-prompting</code> · Version: <code>1.0.0</code> · Family: <code>persona</code>

Assign the expertise the task needs and let it fix the vocabulary, the standards and what counts as a complete answer.

**Strong tasks:** creative_writing, research.  
**Acceptable tasks:** summarization, classification, translation.  
**Minimum calls:** 1; tools not required; evidence documented.

Source: [Prompting GPT-3 To Be Reliable](https://arxiv.org/abs/2210.09150), 2022.

### SimToM (simulated theory of mind)

ID: <code>reasoning.simtom</code> · Version: <code>1.0.0</code> · Family: <code>perspective-taking</code>

Cut the context down to what one participant actually observed, then answer the question from that reduced context alone.

**Strong tasks:** research, classification.  
**Acceptable tasks:** creative_writing, summarization.  
**Minimum calls:** 2; tools not required; evidence documented.

Source: [Think Twice: Perspective-Taking Improves Large Language Models' Theory-of-Mind Capabilities](https://arxiv.org/abs/2311.10227), 2023.

### Plan and execute

ID: <code>reasoning.plan-execute</code> · Version: <code>1.0.0</code> · Family: <code>planning</code>

Create a bounded plan, execute it step by step, and verify the final result.

**Strong tasks:** coding, research, agents.  
**Acceptable tasks:** translation, summarization.  
**Minimum calls:** 2; tools not required; evidence benchmarked.

Source: [Plan-and-Solve Prompting: Improving Zero-Shot Chain-of-Thought Reasoning](https://arxiv.org/abs/2305.04091), 2023.

### Structured chain of thought

ID: <code>coding.structured-cot</code> · Version: <code>1.0.0</code> · Family: <code>program-structure</code>

Reason in the control structures the code will use — sequence, branch, loop — before writing any of it.

**Strong tasks:** coding.  
**Acceptable tasks:** structured_extraction.  
**Minimum calls:** 1; tools not required; evidence documented.

Source: [Structured Chain-of-Thought Prompting for Code Generation](https://arxiv.org/abs/2305.06599), 2023.

### Self-ask

ID: <code>reasoning.self-ask</code> · Version: <code>1.0.0</code> · Family: <code>question-decomposition</code>

Decide whether follow-up questions are needed, answer them, then compose the final answer from those sub-answers.

**Strong tasks:** research.  
**Acceptable tasks:** classification, structured_extraction, summarization.  
**Minimum calls:** 1; tools not required; evidence documented.

Source: [Measuring and Narrowing the Compositionality Gap in Language Models](https://arxiv.org/abs/2210.03350), 2022.

### Verify and edit

ID: <code>verification.verify-and-edit</code> · Version: <code>1.0.0</code> · Family: <code>rationale-repair</code>

Draft the reasoning, turn each shaky step into a question, answer those, and edit the steps the answers contradict.

**Strong tasks:** research, structured_extraction.  
**Acceptable tasks:** classification, coding.  
**Minimum calls:** 2; tools not required; evidence documented.

Source: [Verify-and-Edit: A Knowledge-Enhanced Chain-of-Thought Framework](https://arxiv.org/abs/2305.03268), 2023.

### Self-consistency sampling

ID: <code>reasoning.self-consistency</code> · Version: <code>1.0.0</code> · Family: <code>sampling</code>

Generate several independent solutions and aggregate the most consistent answer.

**Strong tasks:** coding, classification, research.  
**Acceptable tasks:** structured_extraction.  
**Minimum calls:** 3; tools not required; evidence benchmarked.

Source: [Self-Consistency Improves Chain of Thought Reasoning in Language Models](https://arxiv.org/abs/2203.11171), 2022.

### Tree of thoughts

ID: <code>reasoning.tree-of-thought</code> · Version: <code>1.0.0</code> · Family: <code>search</code>

Expand several partial solutions, have the model rank them, keep the best and repeat. Buys accuracy on problems with a wrong-looking first step, at many calls.

**Strong tasks:** coding, research.  
**Acceptable tasks:** classification, structured_extraction.  
**Minimum calls:** 6; tools not required; evidence documented.

Source: [Tree of Thoughts: Deliberate Problem Solving with Large Language Models](https://arxiv.org/abs/2305.10601), 2023.

### Analogical prompting

ID: <code>reasoning.analogical</code> · Version: <code>1.0.0</code> · Family: <code>self-generated-exemplars</code>

Have the model recall its own solved analogues of the problem before answering, so the demonstrations are tailored rather than fixed.

**Strong tasks:** coding, research.  
**Acceptable tasks:** classification, structured_extraction.  
**Minimum calls:** 1; tools not required; evidence documented.

Source: [Large Language Models as Analogical Reasoners](https://arxiv.org/abs/2310.01714), 2023.

### Metacognitive prompting

ID: <code>reasoning.metacognitive</code> · Version: <code>1.0.0</code> · Family: <code>self-reflection</code>

Understand, judge, then criticise that judgement before committing. Aimed at inputs where the first reading is plausible but wrong.

**Strong tasks:** classification, research.  
**Acceptable tasks:** structured_extraction, summarization, coding.  
**Minimum calls:** 1; tools not required; evidence documented.

Source: [Metacognitive Prompting Improves Understanding in Large Language Models](https://arxiv.org/abs/2308.05342), 2023.

### Critique and revise

ID: <code>verification.critique-revise</code> · Version: <code>1.0.0</code> · Family: <code>self-review</code>

Generate a draft, critique it against a rubric, and revise only identified defects.

**Strong tasks:** coding, translation, summarization, creative_writing.  
**Acceptable tasks:** research, structured_extraction.  
**Minimum calls:** 2; tools not required; evidence benchmarked.

Source: [Self-Refine: Iterative Refinement with Self-Feedback](https://arxiv.org/abs/2303.17651), 2023.

### Backward verification

ID: <code>verification.backward-check</code> · Version: <code>1.0.0</code> · Family: <code>self-verification</code>

Answer, then work backwards: given the answer, check it against the input and correct it. This is the verification half of Self-Verification (Weng et al. 2022); the published method also ranks several candidates by verification score, which needs a strategy this registry does not have yet.

**Strong tasks:** structured_extraction, classification.  
**Acceptable tasks:** research, coding, summarization.  
**Minimum calls:** 2; tools not required; evidence documented.

Source: [Large Language Models are Better Reasoners with Self-Verification](https://arxiv.org/abs/2212.09561), 2022.

### Chain of verification (CoVe)

ID: <code>verification.chain-of-verification</code> · Version: <code>1.0.0</code> · Family: <code>self-verification</code>

Draft an answer, generate questions that would expose its errors, answer those, then revise. Three calls, aimed at hallucination.

**Strong tasks:** research, structured_extraction.  
**Acceptable tasks:** summarization, classification, coding.  
**Minimum calls:** 3; tools not required; evidence documented.

Source: [Chain-of-Verification Reduces Hallucination in Large Language Models](https://arxiv.org/abs/2309.11495), 2023.

### Skeleton of thought

ID: <code>reasoning.skeleton-of-thought</code> · Version: <code>1.0.0</code> · Family: <code>structure-first</code>

Produce a bare skeleton of the answer, then flesh it out. Published for latency via parallel expansion; here the skeleton mainly buys structure.

**Strong tasks:** summarization, creative_writing.  
**Acceptable tasks:** research, coding.  
**Minimum calls:** 2; tools not required; evidence documented.

Source: [Skeleton-of-Thought: Prompting LLMs for Efficient Parallel Generation](https://arxiv.org/abs/2307.15337), 2023.

### Schema-first output

ID: <code>structured.schema-first</code> · Version: <code>1.0.0</code> · Family: <code>structured-output</code>

Use a declared schema as the primary output contract and validate the response.

**Strong tasks:** structured_extraction, classification.  
**Acceptable tasks:** coding, summarization.  
**Minimum calls:** 1; tools not required; evidence heuristic.

### Chain of symbol

ID: <code>reasoning.chain-of-symbol</code> · Version: <code>1.0.0</code> · Family: <code>symbolic-representation</code>

Re-express the spatial or relational facts as compact symbols, then reason over the symbols instead of the prose that carried them.

**Strong tasks:** agents, coding.  
**Acceptable tasks:** structured_extraction, research.  
**Minimum calls:** 1; tools not required; evidence documented.

Source: [Chain-of-Symbol Prompting Elicits Planning in Large Language Models](https://arxiv.org/abs/2305.10276), 2023.

### Faithful chain of thought

ID: <code>reasoning.faithful-cot</code> · Version: <code>1.0.0</code> · Family: <code>symbolic-translation</code>

Split the work in two — translate the problem into a symbolic chain, then derive the answer from that chain alone, so the stated reasoning is the reasoning used.

**Strong tasks:** coding, research.  
**Acceptable tasks:** structured_extraction, classification.  
**Minimum calls:** 2; tools not required; evidence documented.

Source: [Faithful Chain-of-Thought Reasoning](https://arxiv.org/abs/2301.13379), 2023.

### Tabular chain of thought

ID: <code>reasoning.tabular-cot</code> · Version: <code>1.0.0</code> · Family: <code>tabular-reasoning</code>

Force the reasoning trace into a markdown table with one row per step, so every step carries a stated operation and result.

**Strong tasks:** coding, structured_extraction.  
**Acceptable tasks:** research, classification.  
**Minimum calls:** 1; tools not required; evidence documented.

Source: [Tabular Representation, Noisy Operators, and Impacts on Table Structure Understanding Tasks](https://arxiv.org/abs/2305.17812), 2023.

### Chain of table

ID: <code>structured.chain-of-table</code> · Version: <code>1.0.0</code> · Family: <code>tabular-transform</code>

Answer a question about tabular data by applying named table operations one at a time and showing the table after each.

**Strong tasks:** structured_extraction, research.  
**Acceptable tasks:** classification, summarization.  
**Minimum calls:** 1; tools not required; evidence documented.

Source: [Chain-of-Table: Evolving Tables in the Reasoning Chain for Table Understanding](https://arxiv.org/abs/2401.04398), 2024.

### Buffer of thoughts

ID: <code>reasoning.buffer-of-thoughts</code> · Version: <code>1.0.0</code> · Family: <code>template-reuse</code>

Distill the reusable solution template for this class of problem, then instantiate it on the instance at hand.

**Strong tasks:** coding, research.  
**Acceptable tasks:** structured_extraction, classification.  
**Minimum calls:** 2; tools not required; evidence documented.

Source: [Buffer of Thoughts: Thought-Augmented Reasoning with Large Language Models](https://arxiv.org/abs/2406.04271), 2024.

### Narrative of thought

ID: <code>reasoning.narrative-of-thought</code> · Version: <code>1.0.0</code> · Family: <code>temporal-reasoning</code>

Retell the events as a story in the order they must have happened, then read the ordering back out of the narrative.

**Strong tasks:** research, structured_extraction.  
**Acceptable tasks:** summarization, creative_writing.  
**Minimum calls:** 1; tools not required; evidence documented.

Source: [Narrative-of-Thought: Improving Temporal Reasoning of Large Language Models via Recounted Narratives](https://arxiv.org/abs/2406.18070), 2024.

### Chain of draft

ID: <code>reasoning.chain-of-draft</code> · Version: <code>1.0.0</code> · Family: <code>thought-generation</code>

Reason in clipped drafts of a few words per step instead of full prose. Aims at chain-of-thought quality at a fraction of the tokens (arXiv 2502.18600).

**Strong tasks:** coding, classification, research.  
**Acceptable tasks:** structured_extraction, summarization.  
**Minimum calls:** 1; tools not required; evidence documented.

Source: [Chain of Draft: Thinking Faster by Writing Less](https://arxiv.org/abs/2502.18600), 2025.

### Zero-shot chain of thought

ID: <code>reasoning.zero-shot-cot</code> · Version: <code>1.0.0</code> · Family: <code>thought-generation</code>

Reason step by step before answering, without any worked examples. Published as a single call; split here so the answer can still obey a schema.

**Strong tasks:** coding, research.  
**Acceptable tasks:** classification, structured_extraction, summarization.  
**Minimum calls:** 2; tools not required; evidence documented.

Source: [Large Language Models are Zero-Shot Reasoners](https://arxiv.org/abs/2205.11916), 2022.

### ReAct tool loop

ID: <code>agents.react</code> · Version: <code>1.0.0</code> · Family: <code>tool-use</code>

Alternate bounded reasoning with tool calls and observations until the goal is satisfied.

**Strong tasks:** agents, research.  
**Acceptable tasks:** coding.  
**Minimum calls:** 2; tools required; evidence benchmarked.

Source: [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629), 2022.

### Glossary-constrained translation

ID: <code>translation.glossary-context</code> · Version: <code>1.0.0</code> · Family: <code>translation-control</code>

Translate with terminology constraints, neighboring context, and a consistency check.

**Strong tasks:** translation.  
**Acceptable tasks:** structured_extraction.  
**Minimum calls:** 1; tools not required; evidence heuristic.

### Tests-first implementation

ID: <code>coding.tests-first</code> · Version: <code>1.0.0</code> · Family: <code>verification</code>

Define observable behavior, implement the smallest change, and validate with tests.

**Strong tasks:** coding.  
**Acceptable tasks:** agents.  
**Minimum calls:** 2; tools not required; evidence heuristic.

