# Tool Contract Sheet — Wren kernel → Fortress executor

The 34 new desktop tools (`runs_on: "desktop"`). Names must match the registry
exactly. Each entry: what it does, what it **takes** (args), what it **returns**.

Return convention: a JSON object; on success `{"status":"succeeded","data":{...}}`,
on failure `{"status":"failed","error":"<reason>"}`. `data` is the useful payload.

---

## ComfyUI (12)

ComfyUI local API is `http://127.0.0.1:8188` unless a different host is configured.

- **list_comfyui_workflows** — list saved workflow templates.
  - takes: `directory` (string, optional — default ComfyUI `user/default/workflows`)
  - returns: `{"workflows":[{"name":str,"path":str}]}`

- **read_comfyui_workflow** — read a workflow's nodes/prompts.
  - takes: `workflow_path` (string, required — path or name)
  - returns: `{"workflow":{...}}` (the workflow JSON)

- **run_comfyui_workflow** — submit a workflow to `/prompt` and start it.
  - takes: `workflow` (object, required — workflow JSON), `client_id` (string, optional)
  - returns: `{"prompt_id":str}`

- **get_comfyui_queue** — current queue (running + pending).
  - takes: *(none)*
  - returns: `{"queue_running":[...],"queue_pending":[...]}`

- **get_comfyui_history** — finished jobs + output image IDs.
  - takes: `prompt_id` (string, optional)
  - returns: `{"history":{...}}`

- **list_comfyui_models** — checkpoints / LoRAs / VAEs / embeddings.
  - takes: `type` (string, optional — `checkpoints|loras|vae|embeddings`)
  - returns: `{"models":[{"name":str,"type":str,"path":str}]}`

- **list_comfyui_nodes** — available node types.
  - takes: *(none)*
  - returns: `{"nodes":[...]}`

- **save_comfyui_workflow** — save/export a workflow JSON.
  - takes: `workflow` (object, required), `name` (string, required)
  - returns: `{"path":str}`

- **edit_comfyui_workflow** — swap checkpoint/LoRA or change a prompt programmatically.
  - takes: `workflow_path` (string, required), `changes` (object, required — e.g. `{"checkpoint":"...","positive_prompt":"..."}`)
  - returns: `{"workflow":{...}}`

- **upload_comfyui_image** — upload an input image for img2img.
  - takes: `image_path` (string, required)
  - returns: `{"name":str,"subfolder":str,"type":str}`

- **get_comfyui_output_image** — fetch a generated image.
  - takes: `filename` (string, required), `subfolder` (string, optional), `type` (string, optional)
  - returns: `{"path":str}`

- **cancel_comfyui_job** — interrupt/remove a queued job.
  - takes: `prompt_id` (string, optional — omit to interrupt all)
  - returns: `{"status":str}`

---

## Image-generation (6)

- **remove_background** — cut out the subject from an image.
  - takes: `image_path` (string, required), `output_path` (string, optional)
  - returns: `{"output_path":str}`

- **inpaint_image** — fill/repair a masked region.
  - takes: `image_path` (string, required), `mask_path` (string, required), `prompt` (string, required), `output_path` (string, optional)
  - returns: `{"output_path":str}`

- **outpaint_image** — extend an image beyond its edges.
  - takes: `image_path` (string, required), `prompt` (string, required), `expand` (string, optional — e.g. `"left"|"right"|"up"|"down"|"all"`), `output_path` (string, optional)
  - returns: `{"output_path":str}`

- **face_swap_image** — swap a face into an image (AuraStyle likeness).
  - takes: `source_image_path` (string, required), `target_image_path` (string, required), `output_path` (string, optional)
  - returns: `{"output_path":str}`

- **train_lora** — train a LoRA from a folder of images.
  - takes: `images_directory` (string, required), `model_name` (string, required), `steps` (integer, optional), `output_path` (string, optional)
  - returns: `{"model_name":str,"output_path":str}`

- **image_to_video** — animate a still into a short clip.
  - takes: `image_path` (string, required), `prompt` (string, optional), `duration` (number, optional), `output_path` (string, optional)
  - returns: `{"output_path":str}`

---

## Video (3)

- **generate_video** — generate a video from a text or image prompt.
  - takes: `prompt` (string, required), `image_path` (string, optional), `duration` (number, optional), `output_path` (string, optional)
  - returns: `{"output_path":str}`

- **trim_video** — trim a clip to a start/end range.
  - takes: `video_path` (string, required), `start` (number, required), `end` (number, required), `output_path` (string, optional)
  - returns: `{"output_path":str}`

- **concat_video** — concatenate multiple clips.
  - takes: `video_paths` (array of strings, required), `output_path` (string, optional)
  - returns: `{"output_path":str}`

---

## Music / audio (2)

- **generate_music** — generate a music track from a text prompt.
  - takes: `prompt` (string, required), `duration` (number, optional), `output_path` (string, optional)
  - returns: `{"output_path":str}`

- **search_music_catalog** — search the studio music catalog.
  - takes: `query` (string, required)
  - returns: `{"results":[{"title":str,"mood":str,"path":str}]}`

---

## Documents (4)

- **create_pdf** — create a PDF from content/markdown.
  - takes: `content` (string, required — markdown or plain text), `output_path` (string, required)
  - returns: `{"output_path":str}`

- **create_docx** — create a Word document.
  - takes: `content` (string, required), `output_path` (string, required)
  - returns: `{"output_path":str}`

- **create_spreadsheet** — create an .xlsx workbook.
  - takes: `sheets` (array of `{"name":str,"rows":[[...]]}`, required), `output_path` (string, required)
  - returns: `{"output_path":str}`

- **create_presentation** — create a PowerPoint deck.
  - takes: `slides` (array of `{"title":str,"body":str}`, required), `output_path` (string, required)
  - returns: `{"output_path":str}`

---

## Deployment (1)

- **deploy_website** — deploy a site to Vercel/Netlify.
  - takes: `project_path` (string, required), `platform` (string, required — `vercel|netlify`)
  - returns: `{"url":str,"status":str}`

---

## Git (5)

- **git_checkout** — check out a branch or commit.
  - takes: `repo_path` (string, required), `branch` (string, required)
  - returns: `{"status":str}`

- **git_branch** — list or create branches.
  - takes: `repo_path` (string, required), `action` (string, optional — `list|create`), `name` (string, optional — required for create)
  - returns: `{"branches":[str]}`

- **git_merge** — merge a branch into the current one.
  - takes: `repo_path` (string, required), `branch` (string, required)
  - returns: `{"status":str}`

- **git_push** — push commits to a remote.
  - takes: `repo_path` (string, required), `remote` (string, optional), `branch` (string, optional)
  - returns: `{"status":str}`

- **git_pull** — pull changes from a remote.
  - takes: `repo_path` (string, required), `remote` (string, optional), `branch` (string, optional)
  - returns: `{"status":str}`

---

## Local data (1)

- **query_local_database** — run a read query against a local SQLite database.
  - takes: `database_path` (string, required), `query` (string, required — SELECT only)
  - returns: `{"columns":[str],"rows":[[...]]}`
