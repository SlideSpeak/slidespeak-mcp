from typing import Any, Optional, Literal
import httpx
import os
import time
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

# Timeouts
DEFAULT_TIMEOUT = 30.0
GENERATION_TIMEOUT = 60.0  # Timeout for the initial generation POST request
POLLING_TIMEOUT = 10.0  # Timeout for each individual status check request


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

    url = f"{API_BASE}{endpoint}"
    req_start = time.time()

    async with httpx.AsyncClient() as client:
        try:
            if method == "POST":
                response = await client.post(url, json=payload, headers=headers, timeout=timeout)
            else:
                response = await client.get(url, headers=headers, timeout=timeout)

            elapsed = time.time() - req_start
            logging.info(f"{method} {url} | status={response.status_code} | elapsed={elapsed:.2f}s")
            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            logging.error(f"HTTP error {method} {url}: {e.response.status_code} - {e.response.text}")
        except httpx.RequestError as e:
            logging.error(f"Request error {method} {url}: {str(e)}")
        except Exception as e:
            logging.error(f"Unexpected error {method} {url}: {str(e)}")

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

    formatted_templates = "Available templates:\n"
    for template in templates_data:
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
    Generate a PowerPoint presentation from text content using specified template.
    Returns a task_id that can be used with getTaskStatus to check progress.
    When the task completes, the result will contain a presentation_id and request_id.
    Use the request_id with the downloadPresentation tool to get the download URL.

    IMPORTANT: This tool returns immediately with a task_id. You MUST then call
    getTaskStatus with the task_id to poll for completion. Keep polling every few
    seconds until the status is SUCCESS or FAILED.

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

    if not API_KEY:
        return "API Key is missing. Cannot process any requests."

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
    if language is not None:
        payload["language"] = language
    if fetch_images is not None:
        payload["fetch_images"] = fetch_images
    if use_document_images is not None:
        payload["use_document_images"] = use_document_images
    if tone is not None:
        payload["tone"] = tone
    if verbosity is not None:
        payload["verbosity"] = verbosity
    if custom_user_instructions is not None and custom_user_instructions.strip():
        payload["custom_user_instructions"] = custom_user_instructions
    if include_cover is not None:
        payload["include_cover"] = include_cover
    if include_table_of_contents is not None:
        payload["include_table_of_contents"] = include_table_of_contents
    if add_speaker_notes is not None:
        payload["add_speaker_notes"] = add_speaker_notes
    if use_general_knowledge is not None:
        payload["use_general_knowledge"] = use_general_knowledge
    if use_wording_from_document is not None:
        payload["use_wording_from_document"] = use_wording_from_document
    if response_format is not None:
        payload["response_format"] = response_format
    if use_branding_logo is not None:
        payload["use_branding_logo"] = use_branding_logo
    if use_branding_fonts is not None:
        payload["use_branding_fonts"] = use_branding_fonts
    if use_branding_color is not None:
        payload["use_branding_color"] = use_branding_color
    if branding_logo is not None:
        payload["branding_logo"] = branding_logo
    if branding_fonts is not None:
        payload["branding_fonts"] = branding_fonts

    # Initiate generation — returns immediately with task_id
    init_result = await _make_api_request("POST", generation_endpoint, payload=payload, timeout=GENERATION_TIMEOUT)

    if not init_result:
        return "Failed to initiate PowerPoint generation due to an API error. Check server logs."

    task_id = init_result.get("task_id")
    if not task_id:
        return f"Failed to initiate PowerPoint generation. API response did not contain a task ID. Response: {init_result}"

    logging.info(f"PowerPoint generation initiated. Task ID: {task_id}")

    return (
        f"Generation started. Task ID: {task_id}\n\n"
        f"The presentation is being generated. Use getTaskStatus with task_id '{task_id}' "
        f"to check progress. Poll every few seconds until status is SUCCESS.\n"
        f"Once complete, use downloadPresentation with the request_id from the task result."
    )


@mcp.tool()
async def generate_slide_by_slide(
    template: str,
    slides: list[dict[str, Any]],
    language: Optional[str] = None,
    fetch_images: Optional[bool] = True,
) -> str:
    """
    Generate a PowerPoint presentation using Slide-by-Slide input.
    Returns a task_id that can be used with getTaskStatus to check progress.

    IMPORTANT: This tool returns immediately with a task_id. You MUST then call
    getTaskStatus with the task_id to poll for completion. Keep polling every few
    seconds until the status is SUCCESS or FAILED.

    Parameters
    - template (string): The name of the template or the ID of a custom template.
    - language (string, optional): Language code like 'ENGLISH' or 'ORIGINAL'.
    - fetch_images (bool, optional): Include stock images (default: True).
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
    - A string with the task_id and instructions to poll for status.
    """
    endpoint = "/presentation/generate/slide-by-slide"

    if not API_KEY:
        return "API Key is missing. Cannot process any requests."

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

    # Initiate generation — returns immediately with task_id
    init_result = await _make_api_request("POST", endpoint, payload=payload, timeout=GENERATION_TIMEOUT)
    if not init_result:
        return "Failed to initiate slide-by-slide generation due to an API error. Check server logs."

    task_id = init_result.get("task_id")
    if not task_id:
        return f"Failed to initiate slide-by-slide generation. API response did not contain a task ID. Response: {init_result}"

    logging.info(f"Slide-by-slide generation initiated. Task ID: {task_id}")

    return (
        f"Generation started. Task ID: {task_id}\n\n"
        f"The presentation is being generated. Use getTaskStatus with task_id '{task_id}' "
        f"to check progress. Poll every few seconds until status is SUCCESS.\n"
        f"Once complete, use downloadPresentation with the request_id from the task result."
    )


@mcp.tool()
async def get_task_status(task_id: str) -> str:
    """
    Get the current task status and result by task ID.
    When the task completes, the result will contain a request_id.
    Use the request_id with the downloadPresentation tool to get the download URL.

    Possible statuses:
    - PENDING: Task is queued
    - SENT: Task has been sent for processing
    - PROCESSING: Task is being processed
    - SUCCESS: Task completed — result contains presentation_id and request_id
    - FAILED: Task failed — result contains error details

    If status is PENDING, SENT, or PROCESSING, poll again in a few seconds.
    """
    if not API_KEY:
        return "API Key is missing. Cannot process any requests."

    status = await _make_api_request("GET", f"/task_status/{task_id}", timeout=POLLING_TIMEOUT)
    if not status:
        return f"Failed to fetch status for task {task_id}."

    task_status = status.get("task_status")
    task_result = status.get("task_result")

    if task_status == "SUCCESS":
        request_id = None
        if isinstance(task_result, dict):
            request_id = task_result.get("request_id")

        result_str = json.dumps(status)
        if request_id:
            result_str += (
                f"\n\nThe presentation is ready! Use downloadPresentation with "
                f"request_id '{request_id}' to get the download URL."
            )
        return result_str

    elif task_status == "FAILED":
        return f"Task {task_id} failed. Details: {json.dumps(status)}"

    elif task_status in ("PENDING", "SENT", "PROCESSING"):
        return (
            f"Task {task_id} is still {task_status.lower()}. "
            f"Please call getTaskStatus again in a few seconds."
        )

    return json.dumps(status)


@mcp.tool()
async def download_presentation(request_id: str) -> str:
    """
    Get the download URL for a generated presentation.
    Use the request_id returned by getTaskStatus (from a completed generation task)
    to get a temporary download link.
    """
    if not API_KEY:
        return "API Key is missing. Cannot process any requests."

    result = await _make_api_request("GET", f"/presentation/download/{request_id}", timeout=DEFAULT_TIMEOUT)
    if not result:
        return f"Failed to get download URL for request {request_id}."

    return f"Make sure to return the download URL to the user. Result: {json.dumps(result)}"


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
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    if not API_KEY:
       logging.critical("SLIDESPEAK_API_KEY is not set. The server cannot communicate with the backend API.")

    mcp.run(transport='stdio')
