// ── 用途选择卡片（T-010：使命卡片——单击直达，身份色体系）──
export interface PurposeCardDef {
  id: string;
  title: string;
  icon: string;
  color: string;
  chips: string[];
  description: string;
}

const PURPOSE_COLORS: Record<string, { border: string; bg: string; text: string; badge: string }> = {
  test: { border: 'border-info/40', bg: 'bg-info/5', text: 'text-info', badge: 'bg-info/15 text-info' },
  req: { border: 'border-purple-500/40', bg: 'bg-purple-900/10', text: 'text-purple-300', badge: 'bg-purple-900/30 text-purple-300' },
};

function getPurposeStyle(colorKey: string) {
  return PURPOSE_COLORS[colorKey] || { border: 'border-border', bg: 'bg-surface-2/40', text: 'text-gray-300', badge: 'bg-surface-3 text-gray-400' };
}

export function PurposeCards({ purposes, onPick }: { purposes: PurposeCardDef[]; onPick: (id: string) => void }) {
  return (
    <div className="flex items-center justify-center min-h-[320px] px-4">
      <div className="flex gap-6 max-w-2xl w-full">
        {purposes.map(p => {
          const style = getPurposeStyle(p.color);
          return (
            <button key={p.id} onClick={() => onPick(p.id)}
              className={`flex-1 flex flex-col items-center gap-3 p-6 rounded-xl border-2 ${style.border} ${style.bg} hover:shadow-lg hover:scale-[1.02] transition-all duration-200 cursor-pointer text-center`}>
              <span className="text-3xl">{p.icon}</span>
              <span className={`text-base font-bold ${style.text}`}>{p.title}</span>
              <p className="text-fs-body text-gray-400 leading-relaxed">{p.description}</p>
              {p.chips && p.chips.length > 0 && (
                <div className="flex flex-wrap gap-1.5 justify-center mt-1">
                  {p.chips.map((chip, ci) => (
                    <span key={ci} className={`text-fs-aux px-2 py-0.5 rounded-full ${style.badge}`}>{chip}</span>
                  ))}
                </div>
              )}
              <span className="text-fs-body text-gray-500 mt-2 border-t border-border/50 pt-2 w-full text-center">点击卡片直接开启会话</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
