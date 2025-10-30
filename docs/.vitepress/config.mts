import { defineConfig } from 'vitepress'
import { tabsMarkdownPlugin } from 'vitepress-plugin-tabs'

// https://vitepress.dev/reference/site-config
export default defineConfig({
  base:'/',
  title: "AgentSight.io",
  description: "A VitePress Site",
  markdown: {
    config(md) {
      md.use(tabsMarkdownPlugin)
    }
  },
  themeConfig: {
    // https://vitepress.dev/reference/default-theme-config
    nav: [
      { text: 'Home', link: '/' },
      { text: 'Quick Start', link: '/getting-started/quick-start' },
      { text: 'API reference', link: '/getting-started/api-reference' }
    ],

    sidebar: [
      {
        text: 'Getting Started',
        collapsed: false,
        items: [
          { text: 'Quickstart', link: '/getting-started/quick-start' },
          { text: 'Core Concepts', link: '/getting-started/core-concepts' },
          // { text: 'Examples', link: '/getting-started/examples' },
          { text: 'Metrics', link: '/getting-started/metrics' },
          { text: 'Configuration', link: '/getting-started/configuration' },
          { text: 'Environments', link: '/getting-started/environments' },
          { text: 'API reference', link: '/getting-started/api-reference' }
        ]
      },
      {
        text: 'Tracking',
        collapsed: false,
        items: [
          { text: 'Track Conversation', link: '/tracking/track-conversations' },
          { text: 'Track Usage Tokens', link: '/tracking/track-tokens' },
          { text: 'Track Interactions', link: '/tracking/track-interaction' },
          { text: 'Track Question', link: '/tracking/track-question' },
          { text: 'Track Answer', link: '/tracking/track-answer' },
          { text: 'Track Attachments', link: '/tracking/track-attachments' },
          { text: 'Track Actions', link: '/tracking/track-actions' },
          { text: 'Track Buttons', link: '/tracking/track-buttons' },
        ]
      },
      {
        text: 'Examples',
        collapsed: false,
        items: [
          { text: 'OpenAI', link: '/examples/openai/openai' },
          { text: 'Anthropic', link: '/examples/anthropic/anthropic' },
          { text: 'LlamaIndex-Fastapi', link: '/examples/llamaindex/llama-index-fastapi' },
          { text: 'LlamaIndex-Flask', link: '/examples/llamaindex/llama-index-flask' },
          { text: 'Langchain-Fastapi', link: '/examples/langchain/langchain-fastapi' },
        ]
      },
    ],

    search: {
      provider: 'local'
    },

    socialLinks: [
      { icon: 'github', link: 'https://github.com/agentsightio/agentsightio' }
    ]
  }
})
