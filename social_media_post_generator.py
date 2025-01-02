import gradio as gr
from openai import OpenAI
import os
import httpx
from phoenix.otel import register
from openinference.instrumentation.openai import OpenAIInstrumentor
from opentelemetry import trace
from openinference.semconv.trace import SpanAttributes

# Configure the Phoenix tracer
tracer_provider = register(
    project_name="social-media-post-generator",
    endpoint="http://localhost:6006/v1/traces",
)

# Set the tracer provider as the global default
trace.set_tracer_provider(tracer_provider)

# Create a tracer instance
tracer = trace.get_tracer(__name__)

# Instrument OpenAI with the tracer provider
OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Prompt template
PROMPT_TEMPLATE = """
You are an expert social media content creator.
Your task is to create a different promotion message with the following 
Product Description :
------
{product_desc}
------
The output promotion message should have the following :
Title: a powerful, short message that dipict what this product is about 
Message: be creative for the promotion message, but make it short and ready for social media feeds, under 100 words.
Tags: the hash tag human will nomally use in social media

Give me the final post, do not have "Title:", "Message:", "Tags:" in it.
Begin!
"""

def send_feedback_to_phoenix(span_id, feedback_type):
    """Send feedback annotation to Phoenix"""
    if not span_id:
        return False
        
    client = httpx.Client()
    label = "👍" if feedback_type == "like" else "👎"
    score = 1 if feedback_type == "like" else 0
    
    try:
        annotation_payload = {
            "data": [
                {
                    "span_id": span_id,
                    "name": "user feedback",
                    "annotator_kind": "HUMAN",
                    "result": {
                        "label": label, 
                        "score": score,
                        "explanation": f"User provided {feedback_type} feedback"
                    },
                    "metadata": {}
                }
            ]
        }

        response = client.post(
            "http://localhost:6006/v1/span_annotations?sync=false", # https://app.phoenix.arize.com/v1/span_annotations?sync=false for cloud instance
            json=annotation_payload
        )
        return response.status_code == 200
    except Exception:
        return False

def generate_post(description):
    try:
        # Create a new span with explicit CHAIN kind
        attributes = {SpanAttributes.OPENINFERENCE_SPAN_KIND: "CHAIN"}
        with tracer.start_as_current_span("Social media post", attributes=attributes) as span:
            # Set input attribute
            span.set_attribute(SpanAttributes.INPUT_VALUE, PROMPT_TEMPLATE.format(product_desc=description))
            
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a helpful social media content creator."},
                    {"role": "user", "content": PROMPT_TEMPLATE.format(product_desc=description)}
                ]
            )
            
            output_content = response.choices[0].message.content
            # Set output attribute
            span.set_attribute(SpanAttributes.OUTPUT_VALUE, output_content)
            
            # Get span context
            span_context = span.get_span_context()
            span_id = format(span_context.span_id, '016x')
            
            return output_content, span_id
    except Exception as e:
        return f"Error generating post: {str(e)}", None

def like_post(data, span_id):
    if span_id and send_feedback_to_phoenix(span_id, "like"):
        return "Thanks for the positive feedback! 👍 (Recorded in Phoenix)"
    return "Thanks for the positive feedback! 👍"

def dislike_post(data, span_id):
    if span_id and send_feedback_to_phoenix(span_id, "dislike"):
        return "Thanks for the feedback! We'll try to improve. 👎 (Recorded in Phoenix)"
    return "Thanks for the feedback! We'll try to improve. 👎"

# Create the Gradio interface
with gr.Blocks() as app:
    gr.Markdown("# Social Media Post Generator")
    
    # Store the span_id for feedback
    span_id_state = gr.State(value=None)
    
    with gr.Row():
        with gr.Column():
            input_text = gr.Textbox(
                label="Product Description",
                placeholder="Enter your product description here...",
                lines=5
            )
            
            with gr.Row():
                generate_btn = gr.Button("Generate Post", variant="primary")
                clear_btn = gr.Button("Clear")
                retry_btn = gr.Button("Retry")

        with gr.Column():
            output_text = gr.Textbox(
                label="Generated Post",
                lines=8,
                interactive=False
            )
            
            with gr.Row():
                like_btn = gr.Button("👍")
                dislike_btn = gr.Button("👎")
            
            feedback_text = gr.Textbox(label="Feedback", interactive=False)

    # Event handlers
    generate_btn.click(
        fn=generate_post,
        inputs=input_text,
        outputs=[output_text, span_id_state]
    )
    
    retry_btn.click(
        fn=generate_post,
        inputs=input_text,
        outputs=[output_text, span_id_state]
    )
    
    clear_btn.click(
        fn=lambda: (None, None, None),
        inputs=None,
        outputs=[input_text, output_text, span_id_state]
    )
    
    like_btn.click(
        fn=like_post,
        inputs=[output_text, span_id_state],
        outputs=feedback_text
    )
    
    dislike_btn.click(
        fn=dislike_post,
        inputs=[output_text, span_id_state],
        outputs=feedback_text
    )

if __name__ == "__main__":
    app.launch() 