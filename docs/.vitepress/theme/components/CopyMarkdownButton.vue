<template>
  <div class="copy-md-div">
    <div class="button-wrapper">
      <button
        class="copy-md-btn"
        :class="{ copied }"
        @click="copy"
        :aria-label="copied ? 'Copied markdown' : 'Copy page as markdown'"
      >
        <!-- Wrapper for icon swap animation -->
        <div class="icon-wrapper">
          <svg v-if="copied" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" class="check-icon"><polyline points="20 6 9 17 4 12"></polyline></svg>
          
          <svg v-else xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="copy-icon"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
        </div>
  
        <span class="label">
          {{ copied ? 'Copied' : 'Copy MD' }}
        </span>
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useData } from 'vitepress'

const { page } = useData()
const copied = ref(false)

async function copy() {
  let md = page.value?.raw
  if (!md) return

  // 1. Remove YAML frontmatter (content between --- and --- at the start)
  md = md.replace(/^---[\s\S]*?---\s*/, '')

  // 2. Remove the <CopyMarkdownButton /> tag itself
  // (matches <CopyMarkdownButton /> with optional spaces)
  md = md.replace(/<CopyMarkdownButton\s*\/>\s*/, '')

  // 3. Trim any remaining leading/trailing whitespace
  md = md.trim()

  try {
    await navigator.clipboard.writeText(md)
    copied.value = true
    
    setTimeout(() => {
      copied.value = false
    }, 2000)
  } catch (e) {
    console.error('Failed to copy', e)
  }
}
</script>

<style scoped>
.copy-md-div {
  display: flex;
  justify-content: end;
}
.button-wrapper {
  display: block;
  border-bottom: 1px solid var(--vp-c-text-2);
  margin-bottom: 12px;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}
.copy-md-btn {
  /* Layout */
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  
  /* Typography */
  font-size: 11px;
  font-weight: 600;
  line-height: 1;
  font-family: var(--vp-font-family-base);
  
  /* Sizing */
  padding: 8px 14px;
  /* border-radius: 8px; */
  
  /* Colors - Default */
  color: var(--vp-c-text-2);
  
  /* Interaction */
  cursor: pointer;
  user-select: none;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}

/* Hover State */
.copy-md-btn:hover {
  color: var(--vp-c-text-1);
  transform: translateY(-1px);
}
.button-wrapper:hover {
  border-bottom: 1px solid var(--vp-c-text-1);
}

/* Active/Click State */
.copy-md-btn:active {
  transform: translateY(1px);
  box-shadow: none;
}

/* --- Copied / Success State --- */
.copy-md-btn.copied {
  color: white;
  background-color: var(--vp-c-green-2);
  border-color: var(--vp-c-green-1);
  box-shadow: 0 0 0 2px var(--vp-c-green-soft);
}

/* Icon Management */
.icon-wrapper {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
}

/* Entry Animation for Checkmark */
.check-icon {
  animation: pop-in 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards;
}

@keyframes pop-in {
  0% { opacity: 0; transform: scale(0.5); }
  100% { opacity: 1; transform: scale(1); }
}

/* Text Adjustment */
.label {
  letter-spacing: 0.2px;
}
</style>