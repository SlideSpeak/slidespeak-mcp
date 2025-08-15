from typing import Any, Optional, Literal
import httpx
import os
import time
import asyncio
import logging
import json
from mcp.server.fastmcp import FastMCP

# --- Configuration & Constants ---

# Initialize FastMCP server
mcp = FastMCP("slidespeak")

# API Configuration
API_BASE = "https://api.slidespeak.co/api/v1"
USER_AGENT = "slidespeak-mcp/0.0.3"
API_KEY = os.environ.get('SLIDESPEAK_API_KEY')

if not API_KEY:
    logging.warning("SLIDESPEAK_API_KEY environment variable not set.")

# Default Timeouts
DEFAULT_TIMEOUT = 30.0
GENERATION_TIMEOUT = 90.0 # Total time allowed for generation + polling
POLLING_INTERVAL = 2.0 # Seconds between status checks
POLLING_TIMEOUT = 10.0 # Timeout for each individual status check request

async def _make_api_request(
    method: Literal["GET", "POST"],
    endpoint: str,
    payload: Optional[dict[str, Any]] = None,
    timeout: float = DEFAULT_TIMEOUT
) -> Optional[dict[str, Any]]:
    """
    Makes an HTTP request to the SlideSpeak API.

    Args:
        method: HTTP method ('GET' or 'POST').
        endpoint: API endpoint path (e.g., '/presentation/templates').
        payload: JSON payload for POST requests. Ignored for GET.
        timeout: Request timeout in seconds.

    Returns:
        The parsed JSON response as a dictionary on success, None on failure.
    """
    if not API_KEY:
        logging.error("API Key is missing. Cannot make API request.")
        return None

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "X-API-Key": API_KEY,
    }

    # Construct full URL
    url = f"{API_BASE}{endpoint}"

    async with httpx.AsyncClient() as client:
        try:
            if method == "POST":
                response = await client.post(url, json=payload, headers=headers, timeout=timeout)
            else: # Default to GET
                response = await client.get(url, headers=headers, timeout=timeout)

            response.raise_for_status() # Raise exception for 4xx or 5xx status codes
            return response.json()

        except httpx.HTTPStatusError as e:
            logging.error(f"HTTP error calling {method} {url}: {e.response.status_code} - {e.response.text}")
        except httpx.RequestError as e:
            logging.error(f"Request error calling {method} {url}: {str(e)}")
        except Exception as e:
            logging.error(f"An unexpected error occurred calling {method} {url}: {str(e)}")

        return None

@mcp.tool()
async def get_available_templates() -> str:
    """Get all available presentation templates."""
    templates_endpoint = "/presentation/templates"

    if not API_KEY:
        return "API Key is missing. Cannot process any requests."

    templates_data = await _make_api_request("GET", templates_endpoint)

    if not templates_data:
        return "Unable to fetch templates due to an API error. Check server logs."

    if not isinstance(templates_data, list):
         return f"Unexpected response format received for templates: {type(templates_data).__name__}"

    if not templates_data:
        return "No templates available."

    formatted_templates = "Available templates:\n"
    for template in templates_data:
        # Add more robust checking for expected keys
        name = template.get("name", "default")
        images = template.get("images", {})
        cover = images.get("cover", "No cover image URL")
        content = images.get("content", "No content image URL")
        formatted_templates += f"- {name}\n  Cover: {cover}\n  Content: {content}\n\n"

    return formatted_templates.strip()

@mcp.tool()
async def get_me() -> str:
    """
    Get details about the current API key (user_name and remaining credits).
    """
    if not API_KEY:
        return "API Key is missing. Cannot process any requests."

    result = await _make_api_request("GET", "/me")
    if not result:
        return "Failed to fetch current user details."
    return json.dumps(result) + "\n Note: Generating slides costs 1 credit / slide"

@mcp.tool()
async def generate_powerpoint(
    plain_text: str,
    length: int,
    template: str,
    document_uuids: Optional[list[str]] = None,
    *,
    language: Optional[str] = "ORIGINAL",
    fetch_images: Optional[bool] = True,
    use_document_images: Optional[bool] = False,
    tone: Optional[Literal['default','casual','professional','funny','educational','sales_pitch']] = 'default',
    verbosity: Optional[Literal['concise','standard','text-heavy']] = 'standard',
    custom_user_instructions: Optional[str] = None,
    include_cover: Optional[bool] = True,
    include_table_of_contents: Optional[bool] = True,
    add_speaker_notes: Optional[bool] = False,
    use_general_knowledge: Optional[bool] = False,
    use_wording_from_document: Optional[bool] = False,
    response_format: Optional[Literal['powerpoint','pdf']] = 'powerpoint',
    use_branding_logo: Optional[bool] = False,
    use_branding_fonts: Optional[bool] = False,
    use_branding_color: Optional[bool] = False,
    branding_logo: Optional[str] = None,
    branding_fonts: Optional[dict[str, str]] = None,
) -> str:
    """
    Generate a PowerPoint or PDF presentation based on text, length, and template.
    Supports optional settings (language, tone, verbosity, images, structure, etc.).
    Waits up to a configured time for the result.

    Parameters:
    Required:
    - plain_text (str): The topic to generate a presentation about
    - length (int): The number of slides
    - template (str): Template name or ID

    Optional:
    - document_uuids (list[str]): UUIDs of uploaded documents to use
    - language (str): Language code (default: 'ORIGINAL')
    - fetch_images (bool): Include stock images (default: True)
    - use_document_images (bool): Include images from documents (default: False)
    - tone (str): Text tone - 'default', 'casual', 'professional', 'funny', 'educational', 'sales_pitch' (default: 'default')
    - verbosity (str): Text length - 'concise', 'standard', 'text-heavy' (default: 'standard')
    - custom_user_instructions (str): Custom generation instructions
    - include_cover (bool): Include cover slide (default: True)
    - include_table_of_contents (bool): Include TOC slides (default: True)
    - add_speaker_notes (bool): Add speaker notes (default: False)
    - use_general_knowledge (bool): Expand with related info (default: False)
    - use_wording_from_document (bool): Use document wording (default: False)
    - response_format (str): 'powerpoint' or 'pdf' (default: 'powerpoint')
    - use_branding_logo (bool): Include brand logo (default: False)
    - use_branding_fonts (bool): Apply brand fonts (default: False)
    - use_branding_color (bool): Apply brand colors (default: False)
    - branding_logo (str): Custom logo URL
    - branding_fonts (dict): The object of brand fonts to be used in the slides
    """
    generation_endpoint = "/presentation/generate"
    status_endpoint_base = "/task_status" # Base path for status checks

    if not API_KEY:
        return "API Key is missing. Cannot process any requests."

    # Prepare the JSON body for the generation request
    # Validate cross-field requirements
    if (use_document_images or use_wording_from_document) and not document_uuids:
        return (
            "When use_document_images or use_wording_from_document is true, you must provide document_uuids."
        )

    payload: dict[str, Any] = {
        "plain_text": plain_text,
        "length": length,
        "template": template,
    }
    if document_uuids:
        payload["document_uuids"] = document_uuids
    if language:
        payload["language"] = language
    if fetch_images:
        payload["fetch_images"] = fetch_images
    if use_document_images:
        payload["use_document_images"] = use_document_images
    if tone:
        payload["tone"] = tone
    if verbosity:
        payload["verbosity"] = verbosity
    if custom_user_instructions is not None and custom_user_instructions.strip():
        payload["custom_user_instructions"] = custom_user_instructions
    if include_cover:
        payload["include_cover"] = include_cover
    if include_table_of_contents:
        payload["include_table_of_contents"] = include_table_of_contents
    if add_speaker_notes:
        payload["add_speaker_notes"] = add_speaker_notes
    if use_general_knowledge:
        payload["use_general_knowledge"] = use_general_knowledge
    if use_wording_from_document:
        payload["use_wording_from_document"] = use_wording_from_document
    if response_format:
        payload["response_format"] = response_format
    if use_branding_logo:
        payload["use_branding_logo"] = use_branding_logo
    if use_branding_fonts:
        payload["use_branding_fonts"] = use_branding_fonts
    if use_branding_color:
        payload["use_branding_color"] = use_branding_color
    if branding_logo:
        payload["branding_logo"] = branding_logo
    if branding_fonts:
        payload["branding_fonts"] = branding_fonts

    # Step 1: Initiate generation (POST request)
    init_result = await _make_api_request("POST", generation_endpoint, payload=payload, timeout=GENERATION_TIMEOUT)

    if not init_result:
        return "Failed to initiate PowerPoint generation due to an API error. Check server logs."

    task_id = init_result.get("task_id")
    if not task_id:
        return f"Failed to initiate PowerPoint generation. API response did not contain a task ID. Response: {init_result}"

    logging.info(f"PowerPoint generation initiated. Task ID: {task_id}")

    # Step 2: Poll for the task status
    status_endpoint = f"{status_endpoint_base}/{task_id}"
    start_time = time.time()
    final_result = None

    while time.time() - start_time < GENERATION_TIMEOUT:
        logging.debug(f"Polling status for task {task_id}...")
        status_result = await _make_api_request("GET", status_endpoint, timeout=POLLING_TIMEOUT)

        if status_result:
            task_status = status_result.get("task_status")
            task_result = status_result.get("task_result") # Assuming result might be here

            if task_status == "SUCCESS":
                logging.info(f"Task {task_id} completed successfully.")
                # Prefer task_result if available, otherwise return the whole status dict as string
                final_result = str(task_result) if task_result else str(status_result)

                final_result = f"Make sure to return the pptx url to the user if available. Here is the result: {final_result}"
                break
            elif task_status == "FAILED": # Use 'FAILED' consistently if possible in API
                logging.error(f"Task {task_id} failed. Status response: {status_result}")
                error_message = task_result.get("error", "Unknown error") if isinstance(task_result, dict) else "Unknown error"
                final_result = f"PowerPoint generation failed for task {task_id}. Reason: {error_message}"
                break
            elif task_status == "PENDING" or task_status == "PROCESSING" or task_status == "SENT": # Add other intermediate states if known
                logging.debug(f"Task {task_id} status: {task_status}. Waiting...")
            else:
                 logging.warning(f"Task {task_id} has unknown status: {task_status}. Response: {status_result}")
                 # Continue polling, but log this unexpected state

        else:
            # Failure during polling
            logging.warning(f"Failed to get status for task {task_id} during polling. Will retry.")
            # Optionally add a counter to break after several consecutive polling failures

        await asyncio.sleep(POLLING_INTERVAL) # Use asyncio.sleep in async functions

    # After loop: check if we got a result or timed out
    if final_result:
        return final_result
    else:
        logging.warning(f"Timeout ({GENERATION_TIMEOUT}s) while waiting for PowerPoint generation task {task_id}.")
        return f"Timeout while waiting for PowerPoint generation (Task ID: {task_id}). The task might still be running."


@mcp.tool()
async def generate_slide_by_slide(
    template: str,
    slides: list[dict[str, Any]],
    language: Optional[str] = None,
    fetch_images: Optional[bool] = True,
) -> str:
    """
    Generate a PowerPoint presentation using Slide-by-Slide input.

    Parameters
    - template (string): The name of the template or the ID of a custom template. See the custom templates section for more information.
    - language (string, optional): Language code like 'ENGLISH' or 'ORIGINAL'.
    - include_cover (bool, optional): Whether to include a cover slide in addition to the specified slides.
    - include_table_of_contents (bool, optional): Whether to include the ‘table of contents’ slides.
    - slides (list[dict]): A list of slides, each defined as a dictionary with the following keys:
      - title (string): The title of the slide.
      - layout (string): The layout type for the slide. See available layout options below.
      - item_amount (integer): Number of items for the slide (must match the layout constraints).
      - content (string): The content that will be used for the slide.

    Available Layouts
    - items: 1-5 items
    - steps: 3-5 items
    - summary: 1-5 items
    - comparison: exactly 2 items
    - big-number: 1-5 items
    - milestone: 3-5 items
    - pestel: exactly 6 items
    - swot: exactly 4 items
    - pyramid: 1-5 items
    - timeline: 3-5 items
    - funnel: 3-5 items
    - quote: 1 item
    - cycle: 3-5 items
    - thanks: 0 items

    Returns
    - A string containing the final task result (including the PPTX URL when available),
      or an error/timeout message.
    """
    endpoint = "/presentation/generate/slide-by-slide"
    status_endpoint_base = "/task_status"

    if not API_KEY:
        return "API Key is missing. Cannot process any requests."

    # Basic validation
    if not isinstance(slides, list) or len(slides) == 0:
        return "Parameter 'slides' must be a non-empty list of slide objects."

    payload: dict[str, Any] = {
        "template": template,
        "slides": slides,
    }
    if language:
        payload["language"] = language
    if fetch_images is not None:
        payload["fetch_images"] = fetch_images

    # Step 1: Initiate slide-by-slide generation
    init_result = await _make_api_request("POST", endpoint, payload=payload, timeout=GENERATION_TIMEOUT)
    if not init_result:
        return "Failed to initiate slide-by-slide generation due to an API error. Check server logs."

    task_id = init_result.get("task_id")
    if not task_id:
        return f"Failed to initiate slide-by-slide generation. API response did not contain a task ID. Response: {init_result}"

    logging.info(f"Slide-by-slide generation initiated. Task ID: {task_id}")

    # Step 2: Poll for the task status
    status_endpoint = f"{status_endpoint_base}/{task_id}"
    start_time = time.time()
    final_result: Optional[str] = None

    while time.time() - start_time < GENERATION_TIMEOUT:
        logging.debug(f"Polling status for task {task_id} (slide-by-slide)...")
        status_result = await _make_api_request("GET", status_endpoint, timeout=POLLING_TIMEOUT)

        if status_result:
            task_status = status_result.get("task_status")
            task_result = status_result.get("task_result")

            if task_status == "SUCCESS":
                logging.info(f"Task {task_id} completed successfully (slide-by-slide).")
                final_result = str(task_result) if task_result else str(status_result)
                final_result = (
                    f"Make sure to return the pptx url to the user if available. Here is the result: {final_result}"
                )
                break
            elif task_status == "FAILED":
                logging.error(f"Task {task_id} failed (slide-by-slide). Status response: {status_result}")
                error_message = (
                    task_result.get("error", "Unknown error") if isinstance(task_result, dict) else "Unknown error"
                )
                final_result = f"Slide-by-slide generation failed for task {task_id}. Reason: {error_message}"
                break
            elif task_status in ("PENDING", "PROCESSING", "SENT"):
                logging.debug(f"Task {task_id} status: {task_status}. Waiting...")
            else:
                logging.warning(
                    f"Task {task_id} has unknown status: {task_status}. Response: {status_result}"
                )
        else:
            logging.warning(
                f"Failed to get status for task {task_id} during polling (slide-by-slide). Will retry."
            )

        await asyncio.sleep(POLLING_INTERVAL)

    if final_result:
        return final_result
    else:
        logging.warning(
            f"Timeout ({GENERATION_TIMEOUT}s) while waiting for slide-by-slide task {task_id}."
        )
        return (
            f"Timeout while waiting for slide-by-slide generation (Task ID: {task_id}). The task might still be running."
        )

@mcp.tool()
async def get_task_status(task_id: str) -> str:
    """
    Get the current task status and result by task_id.
    """
    if not API_KEY:
        return "API Key is missing. Cannot process any requests."
    status = await _make_api_request("GET", f"/task_status/{task_id}", timeout=POLLING_TIMEOUT)
    if not status:
        return f"Failed to fetch status for task {task_id}."
    return json.dumps(status)

@mcp.tool()
async def upload_document(file_path: str) -> str:
    """
    Upload a document file and return the task_id for processing.
    Supported file types: .pptx, .ppt, .docx, .doc, .xlsx, .pdf
    """
    if not API_KEY:
        return "API Key is missing. Cannot process any requests."

    url = f"{API_BASE}/document/upload"
    headers = {
        "User-Agent": USER_AGENT,
        "X-API-Key": API_KEY,
    }

    # Validate path
    if not os.path.isfile(file_path):
        return f"File not found: {file_path}"

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            with open(file_path, "rb") as f:
                files = {"file": (os.path.basename(file_path), f)}
                response = await client.post(url, headers=headers, files=files)
                response.raise_for_status()
                data = response.json()
                return json.dumps(data)
    except httpx.HTTPStatusError as e:
        logging.error(f"HTTP error uploading document: {e.response.status_code} - {e.response.text}")
        return f"Upload failed: {e.response.status_code} {e.response.text}"
    except Exception as e:
        logging.error(f"Unexpected error uploading document: {str(e)}")
        return f"Upload failed: {str(e)}"


if __name__ == "__main__":
    # Configure logging (optional but recommended)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    # Check for API Key at startup
    if not API_KEY:
       logging.critical("SLIDESPEAK_API_KEY is not set. The server cannot communicate with the backend API.")
       # Optionally exit here if the API key is absolutely required
       # import sys
       # sys.exit("API Key missing. Exiting.")

    # Initialize and run the server
    mcp.run(transport='stdio')