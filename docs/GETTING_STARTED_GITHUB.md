# Getting Started with Git & GitHub

**A no-prior-knowledge guide for the BRERC Dashboard team.**

> 👋 **New to all this? You're in the right place.** This guide assumes you have *never* used Git, GitHub, or a terminal. We'll go slowly, explain the jargon, and give you commands you can copy and paste. **Everyone finds this fiddly at first — that's completely normal.** You won't break anything by reading and trying.

Related docs: [`../README.md`](../README.md) · [`../CONTRIBUTING.md`](../CONTRIBUTING.md) · [`./PROJECT_STRUCTURE.md`](./PROJECT_STRUCTURE.md)

---

## Contents

1. [What are Git and GitHub?](#1-what-are-git-and-github)
2. [One-time setup](#2-one-time-setup-do-this-once)
3. [Get the project onto your computer](#3-get-the-project-onto-your-computer)
4. [🌟 The Golden Rules](#4--the-golden-rules)
5. [The everyday workflow](#5-the-everyday-workflow)
6. [After your work is merged](#6-after-your-work-is-merged)
7. [Common problems & exact fixes](#7-common-problems--exact-fixes)
8. [One-page cheat-sheet](#8-one-page-cheat-sheet)

---

## A note on the "terminal" first

Most commands in this guide are typed into a **terminal** (also called a "command line" or "shell"). It's just a window where you type instructions instead of clicking buttons. Don't worry — it looks intimidating, but you'll only need a handful of commands.

| Your computer | How to open the terminal |
| --- | --- |
| 🍎 **macOS** | Press `Cmd + Space` (this opens a search bar called Spotlight), type **Terminal**, then press `Enter`. |
| 🪟 **Windows** | After installing Git (Section 2), open the Start menu, type **Git Bash**, and press `Enter`. This guide's commands are written for **Git Bash**, so please use it rather than the default Command Prompt or PowerShell. |

> 💡 **How to "run" a command:** click into the terminal window, paste the command (right-click to paste, or `Cmd + V` on Mac / `Shift + Insert` in Git Bash), and press `Enter`. That's it.

---

## 1. What are Git and GitHub?

**Git** is a tool that saves snapshots of your work as you go — think of it like **save-points in a video game**. Each time you "commit", you create a save-point you can return to. If something goes wrong, your earlier save-points are safe. Git runs on your own computer.

**GitHub** is a website that stores a **shared cloud copy** of the project that the whole team can reach — think of it as **the shared Google Drive folder for our code**, but built for Git. Everyone pushes their save-points up to GitHub so teammates can see them, review them, and combine everyone's work. Our project lives at **https://github.com/michaelsamuel2005/brerc-dashboard**.

> In short: **Git** = your local save-points. **GitHub** = the team's cloud copy where everyone's work comes together.

---

## 2. One-time setup (do this once)

You only need to do this section **once per computer**. After that, you're set up for good.

### Step 2.1 — Install Git

| Your computer | How to install |
| --- | --- |
| 🍎 **macOS** | Easiest: go to **https://git-scm.com**, download the macOS installer, and run it. *(Or, if you already use Homebrew: `brew install git`.)* |
| 🪟 **Windows** | Go to **https://git-scm.com**, download the Windows installer, and run it. You can accept the default options by clicking **Next** through the installer. This also installs **Git Bash**, the terminal you'll use. |

**Check it worked.** Open your terminal (Terminal on Mac, Git Bash on Windows) and type:

```bash
git --version
```

If you see something like `git version 2.43.0`, you're good. If it says "command not found", the install didn't finish — close and reopen the terminal, or reinstall.

### Step 2.2 — Create a GitHub account

1. Go to **https://github.com** and click **Sign up**.
2. Choose a username, email, and password. A free account is all you need.
3. Verify your email when GitHub asks.

### Step 2.3 — Ask to be added to the repository

A **repository** (or "repo") is just the project's folder on GitHub. Ours is private to the team, so you can't reach it until someone adds you. **Message Michael or Aman with your GitHub username** and ask to be added as a collaborator. Until you're added, you won't be able to download or upload the project.

> ✉️ **What to send:** "Hi, my GitHub username is `your-username-here` — please add me to the brerc-dashboard repo. Thanks!"
>
> After they add you, GitHub will email you an invitation — **click the link in that email and accept it** before moving on.

### Step 2.4 — Tell Git who you are

Git stamps your name and email on every save-point so the team knows who did what. Run these two commands once, replacing the details with **your own name and the email you used for GitHub**:

```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

> 💡 Use the **same email** you signed up to GitHub with — it links your save-points to your GitHub profile.

### Step 2.5 — Set up sign-in (do this now — it saves pain later)

The first time you send work up to GitHub (a "push", covered in Section 5), GitHub needs to confirm it's really you. **Setting this up in advance is the smoothest path**, and the easiest way is the **GitHub CLI** — a small helper tool that handles sign-in for you with friendly on-screen prompts, so you never have to deal with passwords or tokens.

1. Install it from **https://cli.github.com** (download and run the installer, just like Git).
2. Then, in your terminal, run:

```bash
gh auth login
```

3. Answer the prompts by pressing `Enter` to accept the sensible defaults. When it asks how to authenticate, choose **"Login with a web browser"** — it shows you a short code, opens GitHub in your browser, and you paste the code and click **Authorize**. Done.

> 😌 **A login prompt or browser window opening is completely normal — don't panic.** This is GitHub simply checking it's you.

> 💡 **Prefer not to install the CLI?** You can skip it. In that case, the first time you push (Section 5, Step 8) a browser window will usually pop open asking you to log in and click **Authorize** — just do that. If instead the terminal asks you for a username and password, note that GitHub no longer accepts your account password here; you'd need a **Personal Access Token** (a special one-off password). If you hit that, **message Michael or Aman** and they'll walk you through it. The GitHub CLI above avoids this entirely, which is why we recommend it.

Once you've signed in, your computer will usually remember you, so you won't have to do it every time.

---

## 3. Get the project onto your computer

"Cloning" means downloading your own copy of the project from GitHub. Do this **once**.

First, decide **where** you want the project to live — for example, your Documents folder. In the terminal, move there. A safe choice:

```bash
cd ~/Documents
```

> 💡 `cd` means "change directory" (directory = folder). The `~` is a shortcut for your home folder. So this line means "move into the Documents folder inside my home folder."

Then clone the project and move into its folder:

```bash
git clone https://github.com/michaelsamuel2005/brerc-dashboard.git
cd brerc-dashboard
```

- `git clone …` downloads the whole project into a new folder called `brerc-dashboard`.
- `cd brerc-dashboard` moves you **into** that folder. **Almost every git command must be run from inside this folder** — remember this, it's the #1 cause of confusion (see Section 7).

> ✅ **Check you're in the right place:** run `git status`. If it prints information about branches and files (not an error), you're inside the project. 🎉

---

## 4. 🌟 The Golden Rules

> ## 🌟 THREE RULES THAT KEEP US SAFE
>
> 1. **Never work directly on `main`.** `main` is the team's tidy, always-working copy. We never edit it directly.
> 2. **Always make your own branch** for your work — a private workspace where you can't disturb anyone else.
> 3. **One branch per task.** A new task means a new branch, made fresh from an up-to-date `main`.
>
> A **branch** is just your own parallel copy of the project to work on. When it's ready, you'll ask the team to fold it back into `main` through a **Pull Request** (Section 5). Follow these three rules and you literally cannot mess up the team's work.

Branch names follow the pattern **`your-name/short-topic`**, for example:

```
michael/map-legend
aman/readme-updates
victor/api-error-handling
```

> 💡 One more rule worth repeating: **never commit real data or secrets** (passwords, database details, or anything from the `data/` folder). If you're unsure whether something is safe to commit, ask first. See [`../CONTRIBUTING.md`](../CONTRIBUTING.md).

---

## 5. The everyday workflow

This is the routine you'll repeat for **every piece of work**. Follow it top to bottom. 🧭

### Step 1 — Make sure you're in the project folder

```bash
cd ~/Documents/brerc-dashboard
```

*(Adjust the path if you put the project somewhere else. Not sure where you are? See Section 7.)*

### Step 2 — Update your `main` so you start from the latest

```bash
git switch main
git pull
```

- `git switch main` moves you onto the `main` branch.
- `git pull` downloads everyone's latest merged work from GitHub. **Always do this before starting something new** so you build on the newest version.

### Step 3 — Make your own branch for this task

```bash
git switch -c yourname/topic
```

Replace `yourname/topic` with a real name, e.g. `git switch -c michael/species-search`. The `-c` means "create". You're now safely in your own workspace.

### Step 4 — Do your work

Edit files, add features, fix things — using your normal editor (like VS Code). Save your files as usual. Git is quietly noticing every change.

### Step 5 — See what you changed

```bash
git status
```

This lists the files you've added or changed. It's safe to run this as often as you like — it only *looks*, it never changes anything.

### Step 6 — Stage your changes (get them ready to save)

```bash
git add -A
```

"Staging" tells Git which changes to include in your next save-point. `-A` means "all my changes".

### Step 7 — Commit (create the save-point)

```bash
git commit -m "Short description of what you did and why"
```

The bit in quotes is your **commit message** — a short note for your teammates. Write *what* changed and *why*, e.g.:

```bash
git commit -m "Add species search box so users can find records by name"
```

### Step 8 — Push (send your branch up to GitHub)

```bash
git push -u origin yourname/topic
```

Use the **same branch name** you created in Step 3. This uploads your save-points to GitHub so the team can see them. *(First push ever? You may get a login prompt or browser pop-up — that's the normal sign-in from Section 2.5.)*

> 💡 After the first push on a branch, you can just type `git push` for later pushes on the same branch.

### Step 9 — Open a Pull Request on GitHub

A **Pull Request** (PR) is you saying *"here's my finished work — please review it and fold it into `main`."*

1. Go to **https://github.com/michaelsamuel2005/brerc-dashboard** in your browser.
2. You'll usually see a yellow banner near the top: **"Compare & pull request"** — click it. *(If you don't see it, click the **Pull requests** tab, then the green **New pull request** button, and choose your branch from the dropdown.)*
3. Give it a clear **title** (what the work does) and a short **description** (what changed and why).
4. Click the green **Create pull request** button.

### Step 10 — Ask a teammate to review

Message the team chat to say your PR is up (paste the link from your browser). **A teammate looks over your work before it's merged** — this is how we keep `main` healthy, and it's a normal, friendly part of the process, not a test. *(GitHub also has a "Reviewers" box on the right of the PR page where you can request someone specifically, if you know who's reviewing.)*

### Step 11 — Merge

Once a teammate approves, click the green **Merge pull request** button on GitHub, then **Confirm merge**. Your work is now part of `main`. 🎉 GitHub then offers a **Delete branch** button — it's safe to click, and it just tidies up the finished branch.

---

## 6. After your work is merged

Your merged work now lives on GitHub's `main`, but your computer's `main` doesn't know yet. Bring it up to date so your **next** task starts fresh:

```bash
git switch main
git pull
```

Then, when you're ready for a new task, go back to [Section 5, Step 3](#step-3--make-your-own-branch-for-this-task) and make a **brand-new branch**. Never reuse an old, already-merged branch.

---

## 7. Common problems & exact fixes

> 😌 **Before you read on:** none of these mean you've broken anything. They're everyday hiccups that *everyone* hits. Here's exactly what to do.

### ❌ `fatal: not a git repository (or any of the parent directories)`

**What it means:** you're not inside the project folder, so Git doesn't know what you're referring to.

**Fix:** move into the project folder, then try your command again:

```bash
cd ~/Documents/brerc-dashboard
```

*(Use the path where you cloned it. Then re-run whatever command you were trying.)*

### ⚠️ `Your branch is behind 'origin/main' by N commits`

**What it means:** teammates have added work to GitHub that your computer doesn't have yet. Not a problem!

**Fix:** download the latest:

```bash
git pull
```

### ℹ️ `nothing to commit, working tree clean`

**What it means:** there's nothing new to save — everything is already committed. This is **good news**, not an error. You can carry on (e.g. push, or start new work).

### 🔀 A "merge conflict"

**What it means:** you and a teammate changed the **same lines** in the same file, and Git can't decide which version to keep, so it's asking a human. You'll see the word **CONFLICT** in the terminal output.

**Fix:** **Don't panic — this is normal and fixable, and you will *not* lose your work.** Merge conflicts are fiddly the first few times, so the best move is:

> 🙋 **Ask a teammate to sit with you for five minutes.** Resolving conflicts is much easier with someone who's done it before, and nobody will mind helping.

*(If you're comfortable trying yourself: the conflicted file will contain marker lines `<<<<<<<`, `=======`, and `>>>>>>>`. You edit the file to keep the correct combined version, delete those three marker lines, then run `git add -A` and `git commit`. But grabbing a teammate the first time is genuinely the recommended path.)*

### 😬 "I did work on `main` by accident"

**What it means:** you forgot to make a branch and made changes while still on `main`. Easy to recover — **don't panic, and don't commit to `main`.**

**Fix:** move your not-yet-committed changes onto a new branch. Just run:

```bash
git switch -c yourname/topic
```

Your changes come with you onto the new branch, safe and sound. Now continue from [Section 5, Step 5](#step-5--see-what-you-changed). *(If you already committed to `main`, don't push — message Michael or Aman and they'll help you move it across cleanly.)*

### 🧭 "I'm not sure where I am / what's going on"

Two commands tell you everything:

```bash
pwd
```

`pwd` = "print working directory" — shows the **folder you're currently in**. Make sure it ends in `brerc-dashboard`.

```bash
git status
```

`git status` tells you **which branch you're on** and **what's changed**. When in doubt, run these two — they're always safe and never change anything.

> 🆘 **Still stuck?** Copy the exact message you see and send it to the team chat. There's no such thing as a silly question here.

---

## 8. One-page cheat-sheet

Keep this handy. These cover 95% of what you'll ever do.

| I want to… | Command |
| --- | --- |
| Open the terminal | Terminal (Mac) / Git Bash (Windows) |
| Check Git is installed | `git --version` |
| Set my name (once) | `git config --global user.name "Your Name"` |
| Set my email (once) | `git config --global user.email "you@example.com"` |
| Sign in to GitHub (once) | `gh auth login` |
| Download the project (once) | `git clone https://github.com/michaelsamuel2005/brerc-dashboard.git` |
| Go into the project folder | `cd brerc-dashboard` |
| See where I am | `pwd` |
| See what's changed / which branch | `git status` |
| Switch to `main` | `git switch main` |
| Get the latest team work | `git pull` |
| Start a new branch for a task | `git switch -c yourname/topic` |
| Stage all my changes | `git add -A` |
| Save a snapshot (commit) | `git commit -m "what and why"` |
| Send my branch to GitHub (first time) | `git push -u origin yourname/topic` |
| Push again (same branch, later) | `git push` |
| Open a Pull Request | Do it on **github.com** (Section 5, Step 9) |

---

> 💚 **Remember:** the whole point of branches and Pull Requests is that **you can't break the team's work** by experimenting. Try things, make mistakes, ask questions. That's exactly how everyone here learned. You've got this!

**Accessibility note:** the dashboard we're building must meet **WCAG 2.2 AA** (a legal requirement for this public-sector project), so please keep our docs readable too — clear headings, plain language, and descriptive link text. See [`./PROJECT_STRUCTURE.md`](./PROJECT_STRUCTURE.md) for how the repo is laid out.
