import argparse
import asyncio
import os

import gradio as gr
import pandas as pd
import sqlalchemy as sql

from gradio import ChatMessage
from pydantic_ai.usage import UsageLimits

from app.agent_orchestrator import process_user_input_stream, run_agent_orchestrator
from app.visualization_server import serve_visualization


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Multi-Agent Data Analysis Orchestrator")

    parser.add_argument("--prompt", "-p", type=str, help="Analysis prompt or question")
    parser.add_argument(
        "--mode",
        "-m",
        type=str,
        choices=["dataframe", "sql", "auto"],
        default="auto",
        help="Analysis mode: dataframe, sql, or auto-detect",
    )
    parser.add_argument("--file", "-f", type=str, help="Path to data file (.csv, .xlsx)")
    parser.add_argument("--db", "-d", type=str, help="Database connection string")
    parser.add_argument("--stream", "-s", action="store_true", help="Stream output")
    parser.add_argument("--token-limit", type=int, default=4000, help="Maximum total token usage limit")
    parser.add_argument("--request-limit", type=int, default=10, help="Maximum number of requests")

    # For Excel files
    parser.add_argument("--sheet", type=str, help="Sheet name for Excel files")

    return parser.parse_args()


async def run_with_args(args):
    """Run the agent with parsed arguments."""
    if not args.prompt:
        args.prompt = input("Enter your prompt for the data analyst agents: ")

    # Configure usage limits with the correct parameters
    usage_limits = UsageLimits(total_tokens_limit=args.token_limit, request_limit=args.request_limit)

    if args.mode == "sql" or (args.mode == "auto" and args.db):
        # SQL database mode
        if not args.db:
            print("Error: --db parameter is required in SQL mode")
            return {"error": "No database connection specified"}

        if args.stream:
            # Return streaming generator for caller to handle
            return await stream_sql_mode(args, usage_limits)
        # Process normally
        try:
            print(f"Connecting to database: {args.db}")

            # Use the orchestrator to handle everything
            result = await run_agent_orchestrator(user_input=args.prompt, db_url=args.db, usage_limits=usage_limits)

            return result  # noqa: RET504

        except Exception as e:
            print(f"Error connecting to database: {e}")
            return {"error": str(e)}

    elif args.mode == "dataframe" or (args.mode == "auto" and args.file):
        # DataFrame mode
        if not args.file:
            print("Error: --file parameter is required in dataframe mode")
            return {"error": "No file specified"}

        if args.stream:
            # Return streaming generator for caller to handle
            return await stream_dataframe_mode(args, usage_limits)
        # Process normally
        try:
            print(f"Loading data from: {args.file}")

            # Use the orchestrator to handle everything
            result = await run_agent_orchestrator(
                user_input=args.prompt, data_path=args.file, usage_limits=usage_limits
            )

            return result  # noqa: RET504

        except Exception as e:
            print(f"Error loading data: {e}")
            return {"error": str(e)}
    else:
        print("Error: Either --file or --db parameter is required")
        return {"error": "No data source specified"}


async def stream_sql_mode(args, usage_limits):
    """Stream results for SQL mode."""
    try:
        print(f"Connecting to database: {args.db}")
        engine = sql.create_engine(args.db)
        conn = engine.connect()

        # Use streaming version of process_user_input
        async for message in process_user_input_stream(
            user_input=args.prompt, db_connection=conn, usage_limits=usage_limits
        ):
            print(message, end="", flush=True)

        conn.close()
        return {"success": True, "message": "Streaming completed"}

    except Exception as e:
        print(f"Error in SQL streaming mode: {e}")
        return {"error": str(e)}


async def stream_dataframe_mode(args, usage_limits):
    """Stream results for DataFrame mode."""
    try:
        print(f"Loading data from: {args.file}")
        if args.file.endswith(".csv"):
            df = pd.read_csv(args.file)
        elif args.file.endswith((".xls", ".xlsx")):
            df = pd.read_excel(args.file, sheet_name=args.sheet) if args.sheet else pd.read_excel(args.file)
        else:
            print("Unsupported file format. Please use .csv, .xls, or .xlsx")
            return {"error": "Unsupported file format"}

        # Use streaming version of process_user_input
        async for message in process_user_input_stream(user_input=args.prompt, data=df, usage_limits=usage_limits):
            print(message, end="", flush=True)

        return {"success": True, "message": "Streaming completed"}

    except Exception as e:
        print(f"Error in DataFrame streaming mode: {e}")
        return {"error": str(e)}


def display_results(result):
    """Display the results in a user-friendly format."""
    if "error" in result:
        print(f"\n--- Error ---\n{result['error']}")
        return

    print("\n--- Analysis Results ---")

    if result.get("message"):
        print(f"\n{result['message']}")

    if result.get("sql_query"):
        print("\nSQL Query:")
        print(result["sql_query"])

    if result.get("visualization_path"):
        print(f"\nVisualization saved to: {result['visualization_path']}")
        try:
            import webbrowser

            webbrowser.open("file://" + os.path.realpath(result["visualization_path"]))
        except Exception as e:
            print(f"Could not open browser: {e}")

    if result.get("data_summary"):
        print("\nData Summary:")
        shape = result["data_summary"].get("shape")
        if shape:
            print(f"Shape: {shape[0]} rows × {shape[1]} columns")

        columns = result["data_summary"].get("columns")
        if columns:
            print(f"Columns: {', '.join(columns)}")


# Gradio UI implementation
async def process_query(history, prompt, mode, file_upload, db_connection, token_limit, request_limit):  # noqa: C901
    """Process user query and update chat history."""
    if not prompt.strip():
        history.append(ChatMessage(role="assistant", content="Please enter a question or analysis prompt."))
        yield history, gr.update(visible=False)
        return

    # Add user message to history
    history.append(ChatMessage(role="user", content=prompt))
    yield history, gr.update(visible=False)

    # Configure usage limits
    usage_limits = UsageLimits(total_tokens_limit=int(token_limit), request_limit=int(request_limit))

    # Determine the mode
    if mode == "auto":
        if file_upload:
            mode = "dataframe"
        elif db_connection:
            mode = "sql"
        else:
            history.append(
                ChatMessage(
                    role="assistant",
                    content="Please provide either a data file or database connection.",
                    metadata={"title": "❌ Error"},
                )
            )
            yield history, gr.update(visible=False)
            return

    # Process based on mode
    if mode == "sql":
        if not db_connection:
            history.append(
                ChatMessage(
                    role="assistant",
                    content="Database connection string is required for SQL mode.",
                    metadata={"title": "❌ Error"},
                )
            )
            yield history, gr.update(visible=False)
            return

        # Notify user
        history.append(
            ChatMessage(
                role="assistant",
                content=f"Connecting to database: {db_connection}",
                metadata={"title": "🔄 Processing"},
            )
        )
        yield history, gr.update(visible=False)

        try:
            # Stream results
            current_message = ""
            async for message_part in process_user_input_stream(
                user_input=prompt, db_url=db_connection, usage_limits=usage_limits
            ):
                current_message += message_part
                history[-1] = ChatMessage(
                    role="assistant", content=current_message, metadata={"title": "🛠️ Analyzing SQL Data"}
                )
                yield history, gr.update(visible=False)
                await asyncio.sleep(0.01)  # Small delay for smoother streaming

            # Check if visualization was created
            if "visualization saved" in current_message.lower() or "visualization generated" in current_message.lower():
                viz_path = None
                for line in current_message.split("\n"):
                    if "visualization" in line.lower() and ":" in line:
                        viz_path = line.split(":", 1)[1].strip()
                        break

                if viz_path and os.path.exists(viz_path):
                    # Serve the visualization through our HTTP server
                    viz_url = serve_visualization(viz_path)
                    if viz_url:
                        # Create iframe HTML
                        html_content = f"""
                        <div style="width:100%; height:600px; overflow:hidden; border:1px solid #ddd; border-radius:5px;">
                            <iframe src="{viz_url}" width="100%" height="100%" frameborder="0" allowfullscreen></iframe>
                        </div>
                        <div style="text-align:center; margin-top:10px;">
                            <a href="{viz_url}" target="_blank" style="text-decoration:none; padding:8px 16px;
                               background-color:#f0f0f0; border-radius:4px; color:#333;">
                                Open visualization in new tab
                            </a>
                        </div>
                        """

                        # Add message about visualization
                        history.append(
                            ChatMessage(
                                role="assistant",
                                content="Visualization is ready and displayed below.",
                                metadata={"title": "📊 Visualization Ready"},
                            )
                        )

                        # Return updated history and HTML visualization
                        yield history, gr.update(value=html_content, visible=True)
                    else:
                        history.append(
                            ChatMessage(
                                role="assistant",
                                content=f"Visualization created but couldn't be displayed in UI. You can find it at: {viz_path}",
                                metadata={"title": "📊 Visualization Info"},
                            )
                        )
                        yield history, gr.update(visible=False)
                else:
                    yield history, gr.update(visible=False)
            else:
                yield history, gr.update(visible=False)

        except Exception as e:
            history.append(
                ChatMessage(
                    role="assistant", content=f"Error during analysis: {str(e)}", metadata={"title": "❌ Error"}
                )
            )
            yield history, gr.update(visible=False)

    elif mode == "dataframe":
        if not file_upload:
            history.append(
                ChatMessage(
                    role="assistant",
                    content="Please upload a data file (.csv, .xlsx) for DataFrame mode.",
                    metadata={"title": "❌ Error"},
                )
            )
            yield history, gr.update(visible=False)
            return

        # Notify user
        history.append(
            ChatMessage(
                role="assistant",
                content=f"Processing uploaded file: {file_upload.name}",
                metadata={"title": "🔄 Processing"},
            )
        )
        yield history, gr.update(visible=False)

        try:
            # Load dataframe based on file type
            if file_upload.name.endswith(".csv"):
                df = pd.read_csv(file_upload.name)
            elif file_upload.name.endswith((".xls", ".xlsx")):
                df = pd.read_excel(file_upload.name)
            else:
                history.append(
                    ChatMessage(
                        role="assistant",
                        content="Unsupported file format. Please use .csv, .xls, or .xlsx",
                        metadata={"title": "❌ Error"},
                    )
                )
                yield history, gr.update(visible=False)
                return

            # Stream results
            current_message = ""
            async for message_part in process_user_input_stream(user_input=prompt, data=df, usage_limits=usage_limits):
                current_message += message_part
                history[-1] = ChatMessage(
                    role="assistant", content=current_message, metadata={"title": "🛠️ Analyzing Data"}
                )
                yield history, gr.update(visible=False)
                await asyncio.sleep(0.01)

            # Check if visualization was created
            if "visualization saved" in current_message.lower() or "visualization generated" in current_message.lower():
                viz_path = None
                for line in current_message.split("\n"):
                    if "visualization" in line.lower() and ":" in line:
                        viz_path = line.split(":", 1)[1].strip()
                        break

                if viz_path and os.path.exists(viz_path):
                    # Serve the visualization through our HTTP server
                    viz_url = serve_visualization(viz_path)
                    if viz_url:
                        # Create iframe HTML
                        html_content = f"""
                        <div style="width:100%; height:600px; overflow:hidden; border:1px solid #ddd; border-radius:5px;">
                            <iframe src="{viz_url}" width="100%" height="100%" frameborder="0" allowfullscreen></iframe>
                        </div>
                        <div style="text-align:center; margin-top:10px;">
                            <a href="{viz_url}" target="_blank" style="text-decoration:none; padding:8px 16px;
                               background-color:#f0f0f0; border-radius:4px; color:#333;">
                                Open visualization in new tab
                            </a>
                        </div>
                        """

                        # Add message about visualization
                        history.append(
                            ChatMessage(
                                role="assistant",
                                content="Visualization is ready and displayed below.",
                                metadata={"title": "📊 Visualization Ready"},
                            )
                        )

                        # Return updated history and HTML visualization
                        yield history, gr.update(value=html_content, visible=True)
                    else:
                        history.append(
                            ChatMessage(
                                role="assistant",
                                content=f"Visualization created but couldn't be displayed in UI. You can find it at: {viz_path}",
                                metadata={"title": "📊 Visualization Info"},
                            )
                        )
                        yield history, gr.update(visible=False)
                else:
                    yield history, gr.update(visible=False)
            else:
                yield history, gr.update(visible=False)

        except Exception as e:
            history.append(
                ChatMessage(
                    role="assistant", content=f"Error during analysis: {str(e)}", metadata={"title": "❌ Error"}
                )
            )
            yield history, gr.update(visible=False)
    else:
        history.append(
            ChatMessage(
                role="assistant",
                content="Invalid mode selected. Please choose either 'sql', 'dataframe', or 'auto'.",
                metadata={"title": "❌ Error"},
            )
        )
        yield history, gr.update(visible=False)


CUSTOM_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

/* ── Theme Variables ── */
:root {
    --bg-base:        #0a0a0f;
    --bg-panel:       rgba(15,12,41,0.85);
    --bg-input:       rgba(15,12,41,0.9);
    --bg-chat:        rgba(10,10,20,0.95);
    --bg-msg-user:    linear-gradient(135deg,rgba(139,92,246,0.25),rgba(96,165,250,0.15));
    --bg-msg-bot:     rgba(30,27,75,0.6);
    --bg-stat:        linear-gradient(135deg,rgba(15,12,41,0.9),rgba(48,43,99,0.5));
    --bg-hero:        linear-gradient(135deg,#0f0c29,#302b63,#24243e);
    --border-main:    rgba(139,92,246,0.25);
    --border-input:   rgba(139,92,246,0.3);
    --border-stat:    rgba(139,92,246,0.2);
    --border-hero:    rgba(139,92,246,0.3);
    --border-viz:     rgba(52,211,153,0.3);
    --border-clear:   rgba(239,68,68,0.3);
    --border-pipe:    rgba(139,92,246,0.15);
    --text-primary:   #e2e8f0;
    --text-secondary: #94a3b8;
    --text-muted:     #64748b;
    --text-stat:      #a78bfa;
    --text-bot:       #cbd5e1;
    --text-clear:     #f87171;
    --text-footer:    #334155;
    --accent:         #a78bfa;
    --scroll-track:   rgba(15,12,41,0.5);
    --scroll-thumb:   rgba(139,92,246,0.4);
    --tab-color:      #64748b;
    --tab-selected:   #a78bfa;
    --example-bg:     rgba(139,92,246,0.08);
    --example-border: rgba(139,92,246,0.15);
    --example-color:  #a78bfa;
    --footer-border:  rgba(139,92,246,0.1);
    --toggle-bg:      rgba(139,92,246,0.15);
    --toggle-border:  rgba(139,92,246,0.4);
    --toggle-color:   #a78bfa;
    --pipeline-bg:    rgba(139,92,246,0.06);
    --pipeline-border:rgba(139,92,246,0.15);
    --pipeline-label: #64748b;
    --pipeline-text:  #94a3b8;
}

[data-theme="light"] {
    --bg-base:        #f0f4ff;
    --bg-panel:       rgba(255,255,255,0.92);
    --bg-input:       #ffffff;
    --bg-chat:        #ffffff;
    --bg-msg-user:    linear-gradient(135deg,rgba(109,40,217,0.1),rgba(59,130,246,0.07));
    --bg-msg-bot:     rgba(241,245,249,0.95);
    --bg-stat:        linear-gradient(135deg,#ffffff,rgba(237,233,254,0.5));
    --bg-hero:        linear-gradient(135deg,#ede9fe,#dbeafe,#d1fae5);
    --border-main:    rgba(109,40,217,0.2);
    --border-input:   rgba(109,40,217,0.25);
    --border-stat:    rgba(109,40,217,0.15);
    --border-hero:    rgba(109,40,217,0.2);
    --border-viz:     rgba(16,185,129,0.3);
    --border-clear:   rgba(220,38,38,0.25);
    --border-pipe:    rgba(109,40,217,0.12);
    --text-primary:   #1e1b4b;
    --text-secondary: #4b5563;
    --text-muted:     #9ca3af;
    --text-stat:      #6d28d9;
    --text-bot:       #374151;
    --text-clear:     #dc2626;
    --text-footer:    #9ca3af;
    --accent:         #6d28d9;
    --scroll-track:   #f1f5f9;
    --scroll-thumb:   rgba(109,40,217,0.3);
    --tab-color:      #9ca3af;
    --tab-selected:   #6d28d9;
    --example-bg:     rgba(109,40,217,0.06);
    --example-border: rgba(109,40,217,0.12);
    --example-color:  #6d28d9;
    --footer-border:  rgba(109,40,217,0.1);
    --toggle-bg:      rgba(109,40,217,0.1);
    --toggle-border:  rgba(109,40,217,0.3);
    --toggle-color:   #6d28d9;
    --pipeline-bg:    rgba(109,40,217,0.04);
    --pipeline-border:rgba(109,40,217,0.12);
    --pipeline-label: #9ca3af;
    --pipeline-text:  #4b5563;
}

* { box-sizing: border-box; }

body, .gradio-container {
    background: var(--bg-base) !important;
    font-family: 'Inter', sans-serif !important;
    color: var(--text-primary) !important;
    transition: background 0.3s, color 0.3s;
}

.gradio-container {
    max-width: 1400px !important;
    margin: 0 auto !important;
}

/* Hero */
#hero-banner {
    background: var(--bg-hero); border-radius: 20px; padding: 36px 48px;
    margin-bottom: 24px; border: 1px solid var(--border-hero);
    box-shadow: 0 0 60px rgba(139,92,246,0.12), inset 0 1px 0 rgba(255,255,255,0.05);
    position: relative; overflow: hidden;
}
#hero-banner::before {
    content:''; position:absolute; top:-50%; left:-50%; width:200%; height:200%;
    background: radial-gradient(ellipse at center,rgba(139,92,246,0.07) 0%,transparent 60%);
    animation: pulse-bg 6s ease-in-out infinite;
}
@keyframes pulse-bg { 0%,100%{transform:scale(1);opacity:.5} 50%{transform:scale(1.1);opacity:1} }
#hero-banner h1 {
    font-size:2.4rem !important; font-weight:700 !important;
    background: linear-gradient(90deg,#a78bfa,#60a5fa,#34d399) !important;
    -webkit-background-clip:text !important; -webkit-text-fill-color:transparent !important;
    background-clip:text !important; margin:0 0 8px 0 !important; letter-spacing:-0.5px;
}
#hero-banner p { color: var(--text-secondary) !important; font-size:1rem !important; margin:0 !important; }

/* Theme toggle button */
#theme-toggle-btn {
    position: absolute !important; top: 20px !important; right: 20px !important;
    background: var(--toggle-bg) !important; border: 1px solid var(--toggle-border) !important;
    border-radius: 50px !important; color: var(--toggle-color) !important;
    font-size: 0.82rem !important; font-weight: 600 !important; padding: 7px 16px !important;
    cursor: pointer !important; transition: all 0.25s !important; letter-spacing: 0.3px !important;
    backdrop-filter: blur(8px) !important;
}
#theme-toggle-btn:hover { transform: scale(1.05) !important; box-shadow: 0 4px 14px rgba(139,92,246,0.3) !important; }

.badge-row { display:flex; gap:10px; margin-top:16px; flex-wrap:wrap; }
.badge {
    background:rgba(139,92,246,0.15); border:1px solid rgba(139,92,246,0.4);
    color:#a78bfa; padding:4px 12px; border-radius:20px; font-size:0.75rem; font-weight:500; letter-spacing:0.5px;
}
.badge.green { background:rgba(52,211,153,0.1); border-color:rgba(52,211,153,0.4); color:#34d399; }
.badge.blue  { background:rgba(96,165,250,0.1);  border-color:rgba(96,165,250,0.4);  color:#60a5fa; }
[data-theme="light"] .badge       { background:rgba(109,40,217,0.08); border-color:rgba(109,40,217,0.25); color:#6d28d9; }
[data-theme="light"] .badge.green { background:rgba(16,185,129,0.08); border-color:rgba(16,185,129,0.3);  color:#059669; }
[data-theme="light"] .badge.blue  { background:rgba(59,130,246,0.08); border-color:rgba(59,130,246,0.3);  color:#2563eb; }

/* Stats */
.stats-bar { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:24px; }
.stat-card {
    background: var(--bg-stat); border:1px solid var(--border-stat);
    border-radius:12px; padding:16px 20px; text-align:center; transition:border-color 0.3s, background 0.3s;
}
.stat-card:hover { border-color: var(--accent); }
.stat-number { font-size:1.6rem; font-weight:700; color: var(--text-stat); }
.stat-label  { font-size:0.72rem; color: var(--text-muted); text-transform:uppercase; letter-spacing:1px; margin-top:2px; }

/* Chatbot */
#chatbot { background: var(--bg-chat) !important; border:1px solid var(--border-main) !important; border-radius:14px !important; }
#chatbot .message.user {
    background: var(--bg-msg-user) !important; border:1px solid var(--border-input) !important;
    border-radius:12px 12px 2px 12px !important; color: var(--text-primary) !important;
}
#chatbot .message.bot {
    background: var(--bg-msg-bot) !important; border:1px solid rgba(255,255,255,0.06) !important;
    border-radius:12px 12px 12px 2px !important; color: var(--text-bot) !important;
}

/* Input */
#prompt-input textarea {
    background: var(--bg-input) !important; border:1px solid var(--border-input) !important;
    border-radius:12px !important; color: var(--text-primary) !important;
    font-family:'Inter',sans-serif !important; font-size:0.95rem !important;
    padding:14px 16px !important; transition:border-color 0.2s,box-shadow 0.2s;
}
#prompt-input textarea:focus {
    border-color: var(--accent) !important;
    box-shadow:0 0 0 3px rgba(139,92,246,0.1) !important; outline:none !important;
}

/* Buttons */
#submit-btn {
    background:linear-gradient(135deg,#7c3aed,#4f46e5) !important; border:none !important;
    border-radius:12px !important; color:white !important; font-weight:600 !important;
    font-size:0.9rem !important; padding:14px 24px !important; cursor:pointer !important;
    transition:all 0.2s !important; box-shadow:0 4px 15px rgba(124,58,237,0.4) !important;
}
#submit-btn:hover { transform:translateY(-1px) !important; box-shadow:0 6px 20px rgba(124,58,237,0.6) !important; }
#clear-btn {
    background:rgba(239,68,68,0.1) !important; border:1px solid var(--border-clear) !important;
    border-radius:10px !important; color: var(--text-clear) !important; font-weight:500 !important; transition:all 0.2s !important;
}
#clear-btn:hover { background:rgba(239,68,68,0.2) !important; }

/* Mode selector */
.mode-selector .wrap { background: var(--bg-panel) !important; border:1px solid var(--border-stat) !important; border-radius:12px !important; padding:4px !important; }
.mode-selector label { color: var(--text-secondary) !important; font-size:0.85rem !important; font-weight:500 !important; }

/* File upload */
.file-upload { background: var(--bg-panel) !important; border:2px dashed var(--border-input) !important; border-radius:12px !important; transition:border-color 0.2s !important; }
.file-upload:hover { border-color: var(--accent) !important; }

/* Accordion */
.accordion { background: var(--bg-panel) !important; border:1px solid var(--border-pipe) !important; border-radius:12px !important; }

/* Viz panel */
#viz-panel { background: var(--bg-chat); border:1px solid var(--border-viz); border-radius:14px; overflow:hidden; box-shadow:0 0 30px rgba(52,211,153,0.08); }

/* Examples */
.examples-table td {
    background: var(--example-bg) !important; border:1px solid var(--example-border) !important;
    border-radius:8px !important; color: var(--example-color) !important;
    font-size:0.82rem !important; transition:background 0.2s !important; cursor:pointer !important;
}
.examples-table td:hover { background: rgba(139,92,246,0.18) !important; }

/* Section labels */
.section-label { font-size:0.7rem; font-weight:600; text-transform:uppercase; letter-spacing:1.5px; color: var(--text-muted); margin-bottom:8px; }

/* Scrollbar */
::-webkit-scrollbar { width:6px; height:6px; }
::-webkit-scrollbar-track { background: var(--scroll-track); }
::-webkit-scrollbar-thumb { background: var(--scroll-thumb); border-radius:3px; }

/* Tabs */
.tab-nav button { background:transparent !important; border:none !important; color: var(--tab-color) !important; font-weight:500 !important; border-bottom:2px solid transparent !important; transition:all 0.2s !important; }
.tab-nav button.selected { color: var(--tab-selected) !important; border-bottom-color: var(--tab-selected) !important; }

/* DB input */
#db-input textarea, #db-input input {
    background: var(--bg-input) !important; border:1px solid var(--border-stat) !important;
    border-radius:10px !important; color: var(--text-primary) !important;
    font-family:'JetBrains Mono',monospace !important; font-size:0.85rem !important;
}

/* Footer */
#footer { text-align:center; padding:20px; color: var(--text-footer); font-size:0.78rem; border-top:1px solid var(--footer-border); margin-top:24px; }
"""

HERO_HTML = """
<div id="hero-banner">
  <button id="theme-toggle-btn" onclick="toggleTheme()">🌙 Dark</button>
  <h1>⚡ Multi-Agent Data Analyst</h1>
  <p>Powered by GPT-4o · LangGraph · PydanticAI · Plotly — Ask anything about your data</p>
  <div class="badge-row">
    <span class="badge">🤖 Multi-Agent</span>
    <span class="badge blue">📊 Auto Visualization</span>
    <span class="badge green">🗄️ SQL + DataFrame</span>
    <span class="badge">⚡ Streaming</span>
    <span class="badge blue">🔍 Smart Orchestration</span>
  </div>
</div>
<script>
(function() {
  var saved = localStorage.getItem('theme') || 'dark';
  document.documentElement.setAttribute('data-theme', saved);
  function updateBtn() {
    var btn = document.getElementById('theme-toggle-btn');
    if (!btn) return;
    var t = document.documentElement.getAttribute('data-theme');
    btn.textContent = t === 'dark' ? '☀️ Light' : '🌙 Dark';
  }
  window.toggleTheme = function() {
    var current = document.documentElement.getAttribute('data-theme');
    var next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
    updateBtn();
  };
  document.addEventListener('DOMContentLoaded', updateBtn);
  setTimeout(updateBtn, 300);
})();
</script>
"""

STATS_HTML = """
<div class="stats-bar">
  <div class="stat-card"><div class="stat-number">GPT-4o</div><div class="stat-label">AI Engine</div></div>
  <div class="stat-card"><div class="stat-number">3+</div><div class="stat-label">Specialized Agents</div></div>
  <div class="stat-card"><div class="stat-number">CSV · XLS · SQL</div><div class="stat-label">Data Sources</div></div>
  <div class="stat-card"><div class="stat-number">Plotly</div><div class="stat-label">Visualization Engine</div></div>
</div>
"""


def create_gradio_interface():
    """Create and configure the Gradio interface."""
    with gr.Blocks(title="⚡ Multi-Agent Data Analyst", css=CUSTOM_CSS, theme=gr.themes.Base()) as demo:

        gr.HTML(HERO_HTML)
        gr.HTML(STATS_HTML)

        with gr.Row(equal_height=False):
            # ── Left: Chat + Input ──────────────────────────────────────
            with gr.Column(scale=3):
                chatbot = gr.Chatbot(
                    value=[ChatMessage(
                        role="assistant",
                        content="👋 Welcome! Upload a CSV/Excel file or connect a database, then ask me anything about your data. I'll analyze it, write code, and generate interactive visualizations automatically.",
                    )],
                    type="messages",
                    height=480,
                    show_copy_button=True,
                    elem_id="chatbot",
                    avatar_images=(None, "https://api.dicebear.com/7.x/bottts/svg?seed=analyst&backgroundColor=7c3aed"),
                    bubble_full_width=False,
                )

                visualization_html = gr.HTML(
                    visible=False,
                    elem_id="viz-panel",
                )

                with gr.Row():
                    prompt = gr.Textbox(
                        placeholder="💬  Ask anything — 'Show top 10 products by revenue', 'Plot monthly trends', 'Find outliers'...",
                        label="",
                        lines=2,
                        max_lines=4,
                        scale=5,
                        elem_id="prompt-input",
                    )
                    submit_btn = gr.Button("▶ Run", scale=1, elem_id="submit-btn", variant="primary")

                gr.HTML('<div class="section-label" style="margin-top:8px">💡 Quick Prompts</div>')
                gr.Examples(
                    examples=[
                        ["What are the top 5 products by sales?"],
                        ["Show monthly revenue trend as a line chart"],
                        ["Create a heatmap of correlations between all numeric columns"],
                        ["Find and visualize outliers in this dataset"],
                        ["Give me a full statistical summary with charts"],
                        ["Which category has the highest average order value?"],
                    ],
                    inputs=prompt,
                    examples_per_page=6,
                )

            # ── Right: Controls ─────────────────────────────────────────
            with gr.Column(scale=1, min_width=280):

                gr.HTML('<div class="section-label">⚙️ Analysis Mode</div>')
                mode = gr.Radio(
                    ["auto", "dataframe", "sql"],
                    value="auto",
                    label="",
                    info="Auto detects the right agent",
                    elem_classes="mode-selector",
                )

                gr.HTML('<div class="section-label" style="margin-top:16px">📂 Data Source</div>')
                with gr.Tabs():
                    with gr.Tab("📁 File Upload"):
                        file_upload = gr.File(
                            label="Drop CSV or Excel here",
                            file_types=[".csv", ".xlsx", ".xls"],
                            type="filepath",
                            elem_classes="file-upload",
                        )
                    with gr.Tab("🗄️ Database"):
                        db_connection = gr.Textbox(
                            placeholder="sqlite:///mydb.db",
                            label="Connection String",
                            elem_id="db-input",
                        )

                with gr.Accordion("🔧 Advanced", open=False, elem_classes="accordion"):
                    token_limit = gr.Slider(
                        minimum=1000, maximum=16000, value=4000, step=500,
                        label="Token Limit",
                        info="Max tokens per session",
                    )
                    request_limit = gr.Slider(
                        minimum=1, maximum=30, value=10, step=1,
                        label="Request Limit",
                        info="Max API calls",
                    )

                gr.HTML('<div style="margin-top:16px"></div>')
                clear_btn = gr.Button("🗑️ Clear Chat", elem_id="clear-btn")

                gr.HTML("""
                <div style="margin-top:20px; padding:14px; background:var(--pipeline-bg);
                     border:1px solid var(--pipeline-border); border-radius:12px;">
                  <div style="font-size:0.7rem; text-transform:uppercase; letter-spacing:1px;
                       color:var(--pipeline-label); margin-bottom:10px;">🏗️ Agent Pipeline</div>
                  <div style="font-size:0.8rem; color:var(--pipeline-text); line-height:1.8;">
                    🎯 Orchestrator<br>
                    &nbsp;&nbsp;↳ 📊 DataFrame Agent<br>
                    &nbsp;&nbsp;↳ 🗄️ SQL Agent<br>
                    &nbsp;&nbsp;↳ 📈 Visualization Agent
                  </div>
                </div>
                """)

        gr.HTML('<div id="footer">Built with ❤️ using PydanticAI · LangGraph · Gradio · Plotly · OpenAI GPT-4o</div>')

        # Event handlers
        submit_btn.click(
            process_query,
            inputs=[chatbot, prompt, mode, file_upload, db_connection, token_limit, request_limit],
            outputs=[chatbot, visualization_html],
        )
        prompt.submit(
            process_query,
            inputs=[chatbot, prompt, mode, file_upload, db_connection, token_limit, request_limit],
            outputs=[chatbot, visualization_html],
        )
        clear_btn.click(lambda: ([], ""), outputs=[chatbot, prompt])

    return demo


def main():
    """Main entry point."""  # noqa: D401
    # Check if running as script or as gradio app
    if len(os.sys.argv) > 1:
        # Command-line mode
        args = parse_arguments()
        try:
            result = asyncio.run(run_with_args(args))

            if not args.stream:
                display_results(result)

        except Exception as e:
            print(f"Error: {e}")
    else:  # Gradio UI mode
        demo = create_gradio_interface()
        demo.queue()
        port = int(os.environ.get("GRADIO_SERVER_PORT", 7860))
        demo.launch(share=True, server_port=port)


if __name__ == "__main__":
    main()
