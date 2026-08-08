# What's new in the LEAP review tools

This file ships inside the release, so anyone can see what changed between the
copy they have and the one they have been sent.

It is written for the person **using** the tools, not for whoever built them.
Entries say what is different when you run it. Internal work — refactoring,
tests, build machinery — belongs in the commit history, not here.

Each release also records exactly which code and data it was built from, in
`release_manifest.json` beside the program. The version below and the build date
in the program's first line identify a copy; that file identifies it precisely.

---

## 0.3.0

**The opening screen explains itself.**
It now says what the program does — which folder it reads your LEAP exports
from, what the two outputs are, and where they will be written — before asking
anything. It also says what to type: which numbers are valid, that pressing
Enter accepts the value shown in `[brackets]`, and which words the scenario
question expects.

**You can review several years at once.**
The year question now says what the year is *for* — the workbook compares LEAP
against ESTO for the year(s) you name — and accepts more than one:

```
Year(s) [2022]: 2022,2030,2040
```

Each year produces its own workbook and adds a few minutes. Previously a list
was accepted silently and only the first year was used.

**The dashboard is easier to find.**
It was five folders deep, with the economy code repeated twice. That level is
gone, and `OPEN THE DASHBOARD.html` sits at the top of the folder:

```text
output/20_USA/dashboard/OPEN THE DASHBOARD.html     <- open this
output/20_USA/dashboard/dashboards/
output/20_USA/dashboard/chart_bundles/
```

---

## 0.2.0

**Double-clicking now just asks what you want.**
It lists the economies it can see, asks for the economy, the scenario and the
year, and then produces both the balance-review workbook and the dashboard for
that combination. Previously it offered a choice between four commands that
differed by which inputs the code took, and asked for file paths — a question
you could not answer without knowing how the program was built.

**The window no longer closes before you can read it.**
Pressing `l` or `c` printed its answer and vanished instantly. Every screen now
waits for you, including when something goes wrong — which is when the message
matters most.

**A run tells you what it is doing and how long is left.**
A dashboard takes several minutes and used to print nothing at all until it
finished, so a working run looked exactly like a stuck one. It now reports each
step as it starts, with an estimate based on recent runs on your own machine:

```
  [4/5] Comparing LEAP, ESTO and the 9th    done in  1m 56s   (about 7 minutes left)
```

**Real exports are included, so it works out of the box.**
Six economies come with their latest Reference and Target exports already in
`input\leap balances exports\`. You can run something useful immediately, and
the folder shows you the naming rules rather than only describing them.

**The dashboard no longer shows an International bunkers page.**
That page had no LEAP projection behind it, so it invited comparisons that could
not be made. This copy picks up the dashboard fix that removed it.

**A guide with screenshots.**
`LEAP Review Tools - user guide.docx`, beside the program.

### Known limits

* **Demand detail.** Industry and Buildings pages show ESTO and 9th lines but
  almost no LEAP line, because LEAP currently carries demand as a single
  aggregate rather than by sub-sector. The aggregate does appear, on one chart
  per page. This is the state of the model, not a fault in the tools.
* **Bring your own ESTO table.** Supplying a newer ESTO table works, and the
  first run with it takes about two minutes longer while the comparison rows are
  re-derived.

---

## 0.1.0

First release. Two tools — the balance-review workbook and the Common ESTO
dashboard — packaged to run on Windows without Python, Conda, Git, or a copy of
any repository.
