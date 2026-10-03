/** 在脚本里读设计令牌的实际值（ECharts 等画在 canvas 上，不能直接用 CSS 变量）。令牌本身只在 tokens.css 定义。 */
export function cssVar(name: string, fallback = ''): string {
  if (typeof window === 'undefined') return fallback
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}
