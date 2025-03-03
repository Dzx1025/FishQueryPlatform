# chats/services.py
import openai
from django.conf import settings


class AIService:
    """Service for generating AI responses"""

    def __init__(self):
        self.client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)

    def generate_response(self, chat, message_content):
        """Generate AI response for a user message"""
        # Get chat history for context (last N messages)
        # chat_history = self._get_chat_history(chat)
        #
        # # Call OpenAI API
        # response = self.client.chat.completions.create(
        #     model=settings.OPENAI_MODEL,
        #     messages=chat_history + [
        #         {"role": "user", "content": message_content}
        #     ],
        #     max_tokens=settings.OPENAI_MAX_TOKENS,
        #     temperature=settings.OPENAI_TEMPERATURE,
        # )
        #
        # # Extract and return the response text
        # return response.choices[0].message.content
        return "AI response"

    def _get_chat_history(self, chat, max_messages=10):
        """Get the chat history formatted for the AI API"""
        messages = []

        # Get the last N messages
        for message in chat.messages.order_by('-created_at')[:max_messages][::-1]:
            role = "user" if message.message_type == "user" else "assistant"
            messages.append({"role": role, "content": message.content})

        return messages
