# STATUS: where each lane is

One line per lane. Each lane edits only its own line (one writer per line), so git never conflicts.
Milestone IDs only; the plan itself stays with BD.

Format:  LANE: stage <S#> · done <k>/<M> · last done <milestone id> · now <milestone id or idle> · <date>

BD: stage S0 · done 2/3 · last done S0-BD-2 · now S0-BD-3 (waiting: DI and DK read the drafts) · 2026-11-02
DI: stage S0 · done 0/- · last done - · now - · 2026-10-31
DK: stage S0 · done 0/- · last done - · now - · 2026-10-31

## Rule for anyone (person or LLM) before working
1. git pull, then read this file.
2. "Behind" = the other two lanes have finished every milestone of the current stage and this lane still
   has 2 or more open (open = M - k). Say that first, in one line: "DK is behind: 2 open (S1-DK-4, S1-DK-5)".
3. No lane starts stage N+1 until stage N's join check has passed for all three.
4. When you start a milestone, set "now"; when you finish, set "last done" and the date, and commit with the
   milestone ID first in the message (e.g. "S1-DI-3: site directory endpoint").
