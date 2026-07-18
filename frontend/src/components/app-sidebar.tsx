import { Link, useRouterState } from "@tanstack/react-router";
import {
  LayoutDashboard,
  CalendarDays,
  CalendarPlus,
  UserRound,
  Bot,
  BarChart3,
  Settings,
  Stethoscope,
  LifeBuoy,
} from "lucide-react";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarFooter,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";

const mainItems = [
  { title: "لوحة التحكم", url: "/dashboard", icon: LayoutDashboard },
  { title: "المواعيد", url: "/appointments", icon: CalendarDays },
  { title: "حجز موعد", url: "/", icon: CalendarPlus },
  { title: "الأطباء", url: "/doctors", icon: UserRound },
];

const toolsItems = [
  { title: "المساعد الذكي", url: "/ai-assistant", icon: Bot },
  { title: "التحليلات", url: "/analytics", icon: BarChart3 },
  { title: "الإعدادات", url: "/settings", icon: Settings },
];

export function AppSidebar() {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const isActive = (url: string) => pathname === url;

  return (
    <Sidebar side="right" collapsible="icon" className="border-l border-sidebar-border">
      <SidebarHeader className="border-b border-sidebar-border px-3 py-4">
        <div className="flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-soft">
            <Stethoscope className="h-4 w-4" />
          </div>
          <div className="group-data-[collapsible=icon]:hidden">
            <div className="text-sm font-bold leading-tight text-sidebar-foreground">Smart Clinic</div>
            <div className="text-[11px] text-muted-foreground">نظام إدارة العيادات</div>
          </div>
        </div>
      </SidebarHeader>

      <SidebarContent className="px-2 py-3">
        <SidebarGroup>
          <SidebarGroupLabel className="px-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">
            الرئيسية
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu className="gap-0.5">
              {mainItems.map((item) => (
                <NavItem key={item.url} item={item} active={isActive(item.url)} />
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup className="mt-2">
          <SidebarGroupLabel className="px-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">
            الأدوات
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu className="gap-0.5">
              {toolsItems.map((item) => (
                <NavItem key={item.url} item={item} active={isActive(item.url)} />
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="border-t border-sidebar-border p-3 group-data-[collapsible=icon]:hidden">
        <div className="rounded-lg bg-primary-soft p-3">
          <div className="flex items-center gap-2 text-primary">
            <LifeBuoy className="h-4 w-4" />
            <div className="text-xs font-semibold">مركز الدعم</div>
          </div>
          <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
            هل تحتاج مساعدة؟ فريقنا متاح على مدار الساعة.
          </p>
        </div>
      </SidebarFooter>
    </Sidebar>
  );
}

function NavItem({
  item,
  active,
}: {
  item: { title: string; url: string; icon: React.ComponentType<{ className?: string }> };
  active: boolean;
}) {
  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        asChild
        isActive={active}
        tooltip={item.title}
        className="h-9 rounded-lg text-[13px] font-medium data-[active=true]:bg-primary data-[active=true]:text-primary-foreground data-[active=true]:shadow-soft hover:bg-primary-soft hover:text-primary"
      >
        <Link to={item.url} className="flex items-center gap-2.5">
          <item.icon className="h-4 w-4 shrink-0" />
          <span>{item.title}</span>
        </Link>
      </SidebarMenuButton>
    </SidebarMenuItem>
  );
}
