import { defineConfig } from 'vitepress'
import { tabsMarkdownPlugin } from 'vitepress-plugin-tabs'

const siteTitle = "AgentSight.io";
const siteDesc = "Seamlessly track AI conversations, metrics, and deliver client-facing insights and dashboards.";
const siteUrl = "https://docs.agentsight.io";
const ogImage = `${siteUrl}/images/opengraph-image.png`;

export default defineConfig({
  base: '/',
  title: siteTitle,
  description: siteDesc,
  head: [
    // Open Graph
    ['meta', { property: 'og:type', content: 'website' }],
    ['meta', { property: 'og:title', content: siteTitle }],
    ['meta', { property: 'og:description', content: siteDesc }],
    ['meta', { property: 'og:url', content: siteUrl }],
    ['meta', { property: 'og:image', content: `${siteUrl}/images/opengraph-image.png` }],
    ['meta', { property: 'og:site_name', content: siteTitle }],
    ['meta', { property: 'og:image', content: ogImage }],
    ['meta', { property: 'og:image:secure_url', content: ogImage }],
    ['meta', { property: 'og:image:type', content: 'image/png' }],
    ['meta', { property: 'og:image:width', content: '1260' }],
    ['meta', { property: 'og:image:height', content: '630' }],
    ['meta', { property: 'og:image:alt', content: 'AgentSight Documentation Preview Image' }],

    // Twitter (X) Card
    ['meta', { name: 'twitter:card', content: 'summary_large_image' }],
    ['meta', { name: 'twitter:title', content: siteTitle }],
    ['meta', { name: 'twitter:description', content: siteDesc }],
    ['meta', { name: 'twitter:image', content: `${siteUrl}/images/opengraph-image.png` }],
    ['link', { rel: 'icon', href: '/images/favicon.ico' }]
  ],
  markdown: {
    config(md) {
      md.use(tabsMarkdownPlugin)
    }
  },
  themeConfig: {
    logo: {
      light: '/images/agentsight_logo_black.svg',
      dark:'/images/agentsight_logo_white.svg'
    },
    siteTitle: false,
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
        text: 'Clients',
        collapsed: false,
        items: [
          { text: 'ConversationTracker', link: '/clients/tracker' },
          { text: 'ConversationManager', link: '/clients/manager' },
          { text: 'AgentSightAPI', link: '/clients/api' },
        ]
      },
      {
        text: 'Examples',
        collapsed: false,
        items: [
          { text: 'OpenAI', link: '/examples/openai/openai' },
          { text: 'Anthropic', link: '/examples/anthropic/anthropic' },
          { text: 'LlamaIndex-Fastapi', link: '/examples/llamaindex/llama-index-fastapi' },
          { text: 'Langchain-Fastapi', link: '/examples/langchain/langchain-fastapi' },
        ]
      },
      {
        text: 'Tracking',
        collapsed: true,
        items: [
          { text: 'Track Conversation', link: '/tracking/track-conversations' },
          { text: 'Track Usage Tokens', link: '/tracking/track-tokens' },
          { text: 'Track Interactions', link: '/tracking/track-interaction' },
          { text: 'Track Human Message', link: '/tracking/track-question' },
          { text: 'Track Agent Message', link: '/tracking/track-answer' },
          { text: 'Track Attachments', link: '/tracking/track-attachments' },
          { text: 'Track Actions', link: '/tracking/track-actions' },
          { text: 'Track Buttons', link: '/tracking/track-buttons' },
        ]
      },
      {
        text: 'Managing',
        collapsed: true,
        items: [
          { text: 'Add Feedback', link: '/managing/feedback' },
          { text: 'Rename Conversation', link: '/managing/rename' },
          { text: 'Mark Conversation', link: '/managing/mark' },
          { text: 'Delete Conversation', link: '/managing/delete' },
          { text: 'Update Conversation', link: '/managing/update' },
        ]
      },
      {
        text: 'Fetching',
        collapsed: true,
        items: [
          { text: 'Fetch All Conversations', link: '/fetching/conversations' },
          { text: 'Fetch Single Conversation', link: '/fetching/conversation' },
          { text: 'Fetch Conversation Attachments', link: '/fetching/attachments' },
        ]
      }
    ],

    search: {
      provider: 'local'
    },

    socialLinks: [
      { icon: 'github', link: 'https://github.com/agentsightio/agentsightio' }
    ]
  }
})
