# Mechanize Take-Home: Collaborative Whiteboard

Thank you for taking the time to interview with Mechanize! This repo contains your assignment for the final phase of our interview process, an open-ended take-home assignment.

The take-home begins with a solo work block of three hours in which you can complete the task as described below.

There is a 20-minute break after the solo block. During this time, our team will review your submission. If we'd like to move forward based on your progress, we'll talk to you on the follow-up call. If not, we'll cancel the follow-up calendar invite and send you an email cancelling the call.


## Getting started

1. **Clone this repo** (do _not_ fork it):
   ```bash
   git clone <this-repo-url>
   cd <this-repo-name>
   ```
2. See `SETUP.md` for how to run the scaffold.
3. Do all of your work on the **`main` branch**. Commit early and often.
4. **Push your commits directly to `main`** — do not open a pull request.
   ```bash
   git push origin main
   ```
5. Your **final commit must be pushed no later than three hours** after your start time.
   Anything pushed after the deadline will not be considered.

## What you're building

A real-time collaborative whiteboard. Multiple users, same canvas, editing together.

## Deployment context

This whiteboard is for synchronous design reviews, consisting of a small group (typically 2-5 people) on a call together, using the canvas as a shared scratchpad while they talk through a design. 
- Each user has an account and can create canvases or be invited to others'. 
- It's common for several people to be editing at once -- often the same objects -- as they try alternatives or work through a disagreement in real time. 
- A typical session runs 30-90 minutes. 
- Teams sometimes return to a canvas in a later session to recall what was decided.

## Required features

- User accounts (signup, login, logout)
- Create a canvas, open an existing canvas
- Invite other users to a canvas (by username or email -- a simple mechanism is fine)
- Shapes: rectangle, ellipse, line, text
- Select, move, resize, delete, change color
- Undo / redo
- See other users' cursors
- Canvas state persists across sessions

## Out of scope

Don't spend time on these feature, as we won't evaluate them:

- Collaborative text editing within text elements (treating a text update as a single operation is fine -- you don't need to handle two users typing in the same text box simultaneously)
- Granular permissions (viewer/editor/owner roles, share-with-link, etc.)
- Rich text editing, images, or file uploads
- Canvas zoom, pan, or infinite canvas
- Export (PNG, SVG, PDF)
- Version history or named snapshots
- Mobile or touch support

## Provided scaffold

This repository contains a minimal scaffold -- frontend, backend, and database wired together, but no whiteboard logic. You are free to restructure anything in the scaffold, but you are expected to stay within the provided stack; don't swap out the framework or database.

## How we evaluate

We evaluate whether your submission has a functional implementation of all required features above and is fit for the deployment context. Correctness and robustness for this use case and set of features matters more to us than other features beyond the required list, such as those listed as out of scope..

## Use of libraries

Don't pull in libraries that solve the core assignment for you (e.g. [tldraw](https://tldraw.dev/), [yjs](https://yjs.dev/)).

The goal is to assess your engineering skills.

## Use of AI

Use whatever AI tools you like. We recommend that you use frontier AI coding models. We are not aware of a candidate who has performed exceptionally on this take-home without using AI. However, note that you will be expected to **fully understand and defend** your implementation during the call after the solo block.
