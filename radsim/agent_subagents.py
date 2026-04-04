"""Sub-agent orchestration and background-job helpers for the main agent."""

from .output import print_error, print_info, print_success


class AgentSubAgentMixin:
    """Sub-agent orchestration and background-job coordination."""

    def _resolve_subagent_model(self, requested_model):
        """Resolve sub-agent model to an OpenRouter config model."""
        from .sub_agent import resolve_model_name

        resolved = resolve_model_name(requested_model)
        return resolved, "openrouter", ""

    def _prompt_subagent_model(self):
        """Prompt user to select a model for sub-agent tasks."""
        from .menu import interactive_menu
        from .sub_agent import HAIKU_MODEL, get_available_models

        options = [(HAIKU_MODEL, "Claude Haiku 4.5 (Fast & cheap — recommended)")]
        for model_id, description in get_available_models():
            if model_id != HAIKU_MODEL:
                options.append((model_id, description))

        print_info("Select a model for sub-agent tasks (OpenRouter):")
        choice = interactive_menu("SUB-AGENT MODEL", options)

        if choice is None:
            print_info(f"No selection — using Haiku: {HAIKU_MODEL}")
            self._session_capable_model = HAIKU_MODEL
        else:
            self._session_capable_model = choice
            print_success(f"Session model set: {choice}")

        return self._session_capable_model, "openrouter", ""

    def _on_background_job_complete(self, job):
        """Callback when a background job finishes. Prints notification."""
        import sys

        from .output import supports_color

        yellow = "\033[33m" if supports_color() else ""
        green = "\033[32m" if supports_color() else ""
        red = "\033[31m" if supports_color() else ""
        dim = "\033[2m" if supports_color() else ""
        reset = "\033[0m" if supports_color() else ""
        duration = f"{job.duration:.1f}s"

        if job.status.value == "completed":
            icon = green + "+" + reset
            status = "completed"
        else:
            icon = red + "x" + reset
            status = job.status.value

        sys.stdout.write(f"\n{yellow}[{icon} Background job #{job.job_id} {status} ({duration})]{reset}\n")

        if job.status.value == "completed" and job.result_content:
            preview_lines = job.result_content.strip().splitlines()
            max_preview = 15
            for preview_line in preview_lines[:max_preview]:
                sys.stdout.write(f"  {dim}{preview_line[:120]}{reset}\n")
            if len(preview_lines) > max_preview:
                sys.stdout.write(
                    f"  {dim}... ({len(preview_lines) - max_preview} more lines — /bg {job.job_id} for full output){reset}\n"
                )
        elif job.error:
            sys.stdout.write(f"  {red}Error: {job.error[:200]}{reset}\n")

        sys.stdout.write("\n")
        sys.stdout.flush()

    def _collect_finished_background_results(self):
        """Collect results from completed background jobs and inject into messages."""
        from .background import get_job_manager

        manager = get_job_manager()
        injected_ids = getattr(self, "_injected_job_ids", set())

        parts = []
        for job in manager.list_jobs():
            if job.job_id in injected_ids:
                continue
            if job.status.value == "completed" and job.result_content:
                duration = f"{job.duration:.1f}s"
                parts.append(
                    f"[Background job #{job.job_id} COMPLETED ({duration})]\n"
                    f"Task: {job.description}\n"
                    f"Results:\n{job.result_content}"
                )
                injected_ids.add(job.job_id)
            elif job.status.value == "failed":
                parts.append(
                    f"[Background job #{job.job_id} FAILED]\n"
                    f"Task: {job.description}\n"
                    f"Error: {job.error}"
                )
                injected_ids.add(job.job_id)

        self._injected_job_ids = injected_ids
        if parts:
            return "\n\n".join(parts)
        return None

    def _should_stream_subagent(self):
        """Check if sub-agent streaming output is enabled in agent config."""
        from .agent_config import AgentConfigManager

        config_manager = AgentConfigManager()
        return config_manager.get("subagents.stream_output", True)

    def _stream_delegate_task(
        self,
        task_desc,
        model,
        provider,
        api_key,
        system_prompt,
        tools=None,
        max_iterations=10,
    ):
        """Execute a sub-agent task with live streaming output to terminal."""
        import sys

        from .output import supports_color
        from .sub_agent import SubAgentTask, stream_subagent_task

        task = SubAgentTask(
            task_description=task_desc,
            model=model,
            provider=provider,
            api_key=api_key,
            system_prompt=system_prompt,
            tools=tools or [],
            max_iterations=max_iterations,
        )

        dim = "\033[2m" if supports_color() else ""
        cyan = "\033[36m" if supports_color() else ""
        reset = "\033[0m" if supports_color() else ""
        sys.stdout.write(f"\n{dim}{'─' * 40}{reset}\n")
        sys.stdout.write(f"{cyan}  Sub-agent output ({model}):{reset}\n")
        sys.stdout.write(f"{dim}{'─' * 40}{reset}\n")
        sys.stdout.flush()

        generator = stream_subagent_task(task)
        result = None

        try:
            while True:
                chunk = next(generator)
                chunk_type = chunk.get("type", "")
                if chunk_type == "tool_status":
                    sys.stdout.write(f"\n{cyan}  ⚙ {chunk.get('text', '')}{reset}\n")
                    sys.stdout.flush()
                else:
                    text = chunk.get("text", "")
                    sys.stdout.write(f"{dim}{text}{reset}")
                    sys.stdout.flush()
        except StopIteration as stop:
            result = stop.value

        sys.stdout.write(f"\n{dim}{'─' * 40}{reset}\n")
        sys.stdout.flush()
        return result

    def _handle_delegate_task(self, tool_input):
        """Handle delegation to a sub-agent with model selection and parallel support."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from .sub_agent import HAIKU_MODEL, SubAgentResult
        from .sub_agent import delegate_task as subagent_delegate
        from .sub_agent import resolve_task_config

        task_desc = tool_input.get("task_description", "")
        context = tool_input.get("context", "")
        explicit_model = tool_input.get("model", "")
        tier = tool_input.get("tier", "fast")
        parallel_tasks = tool_input.get("parallel_tasks", [])
        system_prompt = tool_input.get("system_prompt", "")

        if explicit_model == "current":
            explicit_model = ""

        tier_config = resolve_task_config(task_desc, tier=tier, model=None)
        tier_tools = tier_config["tools"]

        if context:
            task_desc = f"CONTEXT:\n{context}\n\nTASK:\n{task_desc}"

        background = tool_input.get("background", True)

        if parallel_tasks:
            if not self._session_capable_model and not self._telegram_mode:
                self._prompt_subagent_model()
            session_model = self._session_capable_model or HAIKU_MODEL

            print_info(f"Delegating {len(parallel_tasks)} tasks in parallel (model: {session_model})...")

            def run_parallel():
                results = []
                with ThreadPoolExecutor(max_workers=min(3, len(parallel_tasks))) as executor:
                    futures = {}
                    for index, parallel_task in enumerate(parallel_tasks):
                        future = executor.submit(
                            subagent_delegate,
                            parallel_task.get("task", ""),
                            model=session_model,
                            provider="openrouter",
                            api_key="",
                            system_prompt=parallel_task.get("system_prompt", ""),
                            tools=tier_tools,
                            max_iterations=10,
                        )
                        futures[future] = {"index": index, "model": session_model}

                    for future in as_completed(futures):
                        info = futures[future]
                        try:
                            result = future.result()
                            results.append(
                                {
                                    "index": info["index"],
                                    "model": info["model"],
                                    "success": result.success,
                                    "content": result.content,
                                    "error": result.error,
                                    "input_tokens": result.input_tokens,
                                    "output_tokens": result.output_tokens,
                                }
                            )
                        except Exception as error:
                            results.append(
                                {
                                    "index": info["index"],
                                    "model": info["model"],
                                    "success": False,
                                    "error": str(error),
                                }
                            )

                results.sort(key=lambda item: item["index"])
                success_count = sum(1 for item in results if item.get("success"))

                combined_content = f"Parallel delegation complete: {success_count}/{len(results)} succeeded\n\n"
                for index, result in enumerate(results):
                    status = "✅" if result.get("success") else "❌"
                    combined_content += f"--- Task {index + 1} ({status}) ---\n"
                    if result.get("success"):
                        combined_content += result.get("content", "") + "\n\n"
                    else:
                        combined_content += result.get("error", "") + "\n\n"

                return SubAgentResult(
                    success=success_count > 0,
                    content=combined_content,
                    model_used="multiple",
                    provider_used="openrouter",
                    input_tokens=sum(item.get("input_tokens", 0) for item in results),
                    output_tokens=sum(item.get("output_tokens", 0) for item in results),
                    error="" if success_count > 0 else "Some parallel tasks failed.",
                )

            if background:
                from .background import get_job_manager

                manager = get_job_manager()
                task_descriptions = [task.get("task", "")[:80] for task in parallel_tasks]
                description_summary = " | ".join(task.get("task", "task")[:40] for task in parallel_tasks)

                job = manager.start_job(
                    description=description_summary[:100],
                    run_function=run_parallel,
                    model=session_model,
                    tier=tier,
                    sub_tasks=task_descriptions,
                )
                print_success(f"Background parallel job #{job.job_id} started — /bg {job.job_id} to check")
                return {
                    "success": True,
                    "background": True,
                    "job_id": job.job_id,
                    "message": f"{len(parallel_tasks)} parallel tasks running in background as job #{job.job_id}. Use /bg to check status.",
                }

            sync_result = run_parallel()
            return {
                "success": sync_result.success,
                "content": sync_result.content,
                "models_used": "multiple",
                "input_tokens": sync_result.input_tokens,
                "output_tokens": sync_result.output_tokens,
                "error": sync_result.error,
            }

        if explicit_model:
            resolved_model, resolved_provider, resolved_key = self._resolve_subagent_model(explicit_model)
        elif self._session_capable_model:
            resolved_model = self._session_capable_model
            resolved_provider = "openrouter"
            resolved_key = ""
        elif background or self._telegram_mode:
            resolved_model = HAIKU_MODEL
            resolved_provider = "openrouter"
            resolved_key = ""
        else:
            resolved_model, resolved_provider, resolved_key = self._prompt_subagent_model()

        print_info(f"Delegating task to sub-agent (model: {resolved_model}, tier: {tier})")

        if background:
            from .background import get_job_manager

            manager = get_job_manager()

            def run_background():
                return subagent_delegate(
                    task_desc,
                    model=resolved_model,
                    provider=resolved_provider,
                    api_key=resolved_key,
                    system_prompt=system_prompt,
                    tools=tier_tools,
                    max_iterations=10,
                )

            job = manager.start_job(
                description=task_desc[:100],
                run_function=run_background,
                model=resolved_model,
                tier=tier,
            )
            print_success(f"Background job #{job.job_id} started — /bg {job.job_id} to check")
            return {
                "success": True,
                "background": True,
                "job_id": job.job_id,
                "message": f"Task running in background as job #{job.job_id}. Use /bg to check status.",
            }

        if self._should_stream_subagent():
            result = self._stream_delegate_task(
                task_desc,
                resolved_model,
                resolved_provider,
                resolved_key,
                system_prompt,
                tools=tier_tools,
                max_iterations=10,
            )
        else:
            result = subagent_delegate(
                task_desc,
                model=resolved_model,
                provider=resolved_provider,
                api_key=resolved_key,
                system_prompt=system_prompt,
                tools=tier_tools,
                max_iterations=10,
            )

        if result.success:
            print_success(f"Sub-agent completed (model: {result.model_used})")
            return {
                "success": True,
                "content": result.content,
                "model_used": result.model_used,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
            }

        print_error(f"Sub-agent failed: {result.error}")
        return {
            "success": False,
            "error": result.error,
            "model_used": result.model_used,
        }
