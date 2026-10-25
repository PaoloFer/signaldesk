from __future__ import annotations

from sqlalchemy import (
    Float,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    text as sql_text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SocialComment(Base):
    __tablename__ = "social_comments"
    __table_args__ = (
        Index("idx_comments_published_at", "published_at"),
        Index("idx_comments_niche", "niche"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    content_id: Mapped[str] = mapped_column(Text, nullable=False)
    content_title: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    author_hash: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'YouTube'"))
    niche: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    topic: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))

    project_links: Mapped[list[ProjectComment]] = relationship(back_populates="comment")


class SocialContent(Base):
    __tablename__ = "social_contents"
    __table_args__ = (
        UniqueConstraint("platform", "external_id", name="uq_social_contents_platform_external_id"),
        Index("idx_contents_published_at", "published_at"),
        Index("idx_contents_niche", "niche"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'YouTube'"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    tags_json: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'[]'"))
    channel_id: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    channel_title: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    published_at: Mapped[str] = mapped_column(Text, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))
    views: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))
    likes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))
    comments: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))
    has_paid_product_placement: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sql_text("0")
    )
    niche: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    topic: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    source_query: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    acquired_at: Mapped[str] = mapped_column(Text, nullable=False)

    project_links: Mapped[list[ProjectContent]] = relationship(back_populates="content")
    niche_links: Mapped[list[NicheContent]] = relationship(back_populates="content")
    entity_mentions: Mapped[list[ContentEntityMention]] = relationship(back_populates="content")
    ad_signals: Mapped[list[ContentAdSignal]] = relationship(back_populates="content")


class ContentSnapshot(Base):
    __tablename__ = "content_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "platform", "external_id", "captured_at",
            name="uq_content_snapshots_platform_external_id_captured_at",
        ),
        Index("idx_snapshots_content", "platform", "external_id"),
        Index("idx_snapshots_captured_at", "captured_at"),
        Index("idx_snapshots_external_id", "external_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'YouTube'"))
    captured_at: Mapped[str] = mapped_column(Text, nullable=False)
    views: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))
    likes: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))
    comments: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    projects: Mapped[list[ResearchProject]] = relationship(back_populates="organization")
    memberships: Mapped[list[OrganizationMember]] = relationship(back_populates="organization")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    memberships: Mapped[list[OrganizationMember]] = relationship(back_populates="user")
    sessions: Mapped[list[UserSession]] = relationship(back_populates="user")


class ResearchProject(Base):
    __tablename__ = "research_projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, server_default=sql_text("1")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    transcription_credits: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sql_text("25")
    )
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    organization: Mapped[Organization] = relationship(back_populates="projects")
    contents: Mapped[list[ProjectContent]] = relationship(back_populates="project")
    comments: Mapped[list[ProjectComment]] = relationship(back_populates="project")
    monitoring_runs: Mapped[list[MonitoringRun]] = relationship(back_populates="project")
    background_jobs: Mapped[list[BackgroundJob]] = relationship(back_populates="project")
    sources: Mapped[list[ProjectSource]] = relationship(back_populates="project")
    niches: Mapped[list[Niche]] = relationship(back_populates="project")
    entities: Mapped[list[Entity]] = relationship(back_populates="project")
    entity_mentions: Mapped[list[ContentEntityMention]] = relationship(back_populates="project")
    ad_signals: Mapped[list[ContentAdSignal]] = relationship(back_populates="project")
    channel_profiles: Mapped[list[ChannelProfile]] = relationship(back_populates="project")
    creators: Mapped[list[Creator]] = relationship(back_populates="project")


class ProjectContent(Base):
    __tablename__ = "project_contents"
    __table_args__ = (
        PrimaryKeyConstraint("project_id", "content_id"),
        Index("idx_project_contents_project", "project_id"),
        Index("idx_project_contents_niche", "project_id", "niche"),
    )

    project_id: Mapped[int] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=False
    )
    content_id: Mapped[int] = mapped_column(
        ForeignKey("social_contents.id", ondelete="CASCADE"), nullable=False
    )
    niche: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    topic: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    source_query: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    added_at: Mapped[str] = mapped_column(Text, nullable=False)

    project: Mapped[ResearchProject] = relationship(back_populates="contents")
    content: Mapped[SocialContent] = relationship(back_populates="project_links")


class ProjectComment(Base):
    __tablename__ = "project_comments"
    __table_args__ = (
        PrimaryKeyConstraint("project_id", "comment_id"),
        Index("idx_project_comments_project", "project_id"),
    )

    project_id: Mapped[int] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=False
    )
    comment_id: Mapped[int] = mapped_column(
        ForeignKey("social_comments.id", ondelete="CASCADE"), nullable=False
    )
    niche: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    topic: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    added_at: Mapped[str] = mapped_column(Text, nullable=False)

    project: Mapped[ResearchProject] = relationship(back_populates="comments")
    comment: Mapped[SocialComment] = relationship(back_populates="project_links")


class OrganizationMember(Base):
    __tablename__ = "organization_members"
    __table_args__ = (PrimaryKeyConstraint("organization_id", "user_id"),)

    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'owner'"))

    organization: Mapped[Organization] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")


class UserSession(Base):
    __tablename__ = "user_sessions"
    __table_args__ = (
        Index("idx_sessions_user", "user_id"),
        Index("idx_sessions_expiry", "expires_at"),
    )

    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[str] = mapped_column(Text, nullable=False)

    user: Mapped[User] = relationship(back_populates="sessions")


class MonitoringRun(Base):
    __tablename__ = "monitoring_runs"
    __table_args__ = (Index("idx_monitoring_runs_started_at", sql_text("started_at DESC")),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trigger: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[str] = mapped_column(Text, nullable=False)
    finished_at: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'running'"))
    requested: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))
    received: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))
    updated: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))
    error: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("research_projects.id", ondelete="SET NULL")
    )

    project: Mapped[ResearchProject | None] = relationship(back_populates="monitoring_runs")


class BackgroundJob(Base):
    __tablename__ = "background_jobs"
    __table_args__ = (
        Index("idx_jobs_status_created", "status", "created_at"),
        Index("idx_jobs_project", "project_id", sql_text("created_at DESC")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=False
    )
    job_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'queued'"))
    progress: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))
    result_json: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'{}'"))
    error: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[str | None] = mapped_column(Text)
    cancel_requested: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))

    project: Mapped[ResearchProject] = relationship(back_populates="background_jobs")


class ProjectSource(Base):
    __tablename__ = "project_sources"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "source_type", "config_json",
            name="uq_project_sources_project_type_config",
        ),
        Index("idx_sources_project", "project_id", sql_text("created_at DESC")),
        Index("idx_sources_due", "status", "next_run_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    config_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'active'"))
    refresh_hours: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("24"))
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    last_run_at: Mapped[str | None] = mapped_column(Text)
    next_run_at: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))

    project: Mapped[ResearchProject] = relationship(back_populates="sources")


class Niche(Base):
    __tablename__ = "niches"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_niches_project_name"),
        Index("idx_niches_project", "project_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'draft'"))
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'topic'"))
    definition_json: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=sql_text("'{}'")
    )
    seed_channels_json: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=sql_text("'[]'")
    )
    seed_videos_json: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=sql_text("'[]'")
    )
    include_keywords_json: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=sql_text("'[]'")
    )
    exclude_keywords_json: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=sql_text("'[]'")
    )
    filters_json: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=sql_text("'{}'")
    )
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    project: Mapped[ResearchProject] = relationship(back_populates="niches")
    niche_contents: Mapped[list[NicheContent]] = relationship(back_populates="niche")
    channel_memberships: Mapped[list[NicheChannel]] = relationship(back_populates="niche")


class NicheContent(Base):
    __tablename__ = "niche_contents"
    __table_args__ = (
        PrimaryKeyConstraint("niche_id", "content_id"),
        Index("idx_niche_contents_niche", "niche_id"),
    )

    niche_id: Mapped[int] = mapped_column(
        ForeignKey("niches.id", ondelete="CASCADE"), nullable=False
    )
    content_id: Mapped[int] = mapped_column(
        ForeignKey("social_contents.id", ondelete="CASCADE"), nullable=False
    )
    relevance_score: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=sql_text("0.0")
    )
    matched_seed: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    matched_value: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    added_at: Mapped[str] = mapped_column(Text, nullable=False)

    niche: Mapped[Niche] = relationship(back_populates="niche_contents")
    content: Mapped[SocialContent] = relationship(back_populates="niche_links")


class ChannelProfile(Base):
    __tablename__ = "channel_profiles"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "platform", "channel_id",
            name="uq_channel_profiles_project_platform_channel",
        ),
        Index("idx_channel_profiles_project", "project_id"),
        Index("idx_channel_profiles_platform_channel", "platform", "channel_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=False
    )
    platform: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'YouTube'"))
    channel_id: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    custom_url: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    country: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    default_language: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    subscribers: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))
    video_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))
    themes_json: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'[]'"))
    metrics_json: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'{}'"))
    computed_at: Mapped[str] = mapped_column(Text, nullable=False)

    project: Mapped[ResearchProject] = relationship(back_populates="channel_profiles")
    niche_memberships: Mapped[list[NicheChannel]] = relationship(back_populates="channel_profile")
    creator_links: Mapped[list[CreatorLink]] = relationship(back_populates="channel_profile")


class NicheChannel(Base):
    __tablename__ = "niche_channels"
    __table_args__ = (
        PrimaryKeyConstraint("niche_id", "channel_profile_id"),
        Index("idx_niche_channels_niche", "niche_id"),
        Index("idx_niche_channels_profile", "channel_profile_id"),
    )

    niche_id: Mapped[int] = mapped_column(
        ForeignKey("niches.id", ondelete="CASCADE"), nullable=False
    )
    channel_profile_id: Mapped[int] = mapped_column(
        ForeignKey("channel_profiles.id", ondelete="CASCADE"), nullable=False
    )
    relevance_score: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=sql_text("0.0")
    )
    matched_themes_json: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=sql_text("'[]'")
    )
    added_at: Mapped[str] = mapped_column(Text, nullable=False)

    niche: Mapped[Niche] = relationship(back_populates="channel_memberships")
    channel_profile: Mapped[ChannelProfile] = relationship(back_populates="niche_memberships")


class Creator(Base):
    __tablename__ = "creators"
    __table_args__ = (
        Index("idx_creators_project", "project_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=False
    )
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    project: Mapped[ResearchProject] = relationship(back_populates="creators")
    links: Mapped[list[CreatorLink]] = relationship(back_populates="creator")


class CreatorLink(Base):
    __tablename__ = "creator_links"
    __table_args__ = (
        PrimaryKeyConstraint("creator_id", "channel_profile_id"),
        Index("idx_creator_links_profile", "channel_profile_id"),
    )

    creator_id: Mapped[int] = mapped_column(
        ForeignKey("creators.id", ondelete="CASCADE"), nullable=False
    )
    channel_profile_id: Mapped[int] = mapped_column(
        ForeignKey("channel_profiles.id", ondelete="CASCADE"), nullable=False
    )
    link_method: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'manual'"))
    confidence: Mapped[float] = mapped_column(Float, nullable=False, server_default=sql_text("1.0"))
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    creator: Mapped[Creator] = relationship(back_populates="links")
    channel_profile: Mapped[ChannelProfile] = relationship(back_populates="creator_links")


class CommentAnalysis(Base):
    __tablename__ = "comment_analysis"
    __table_args__ = (
        Index("idx_comment_analysis_sentiment", "sentiment"),
        Index("idx_comment_analysis_intent", "intent"),
    )

    comment_id: Mapped[int] = mapped_column(
        ForeignKey("social_comments.id", ondelete="CASCADE"), primary_key=True
    )
    language: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    sentiment: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'neutral'"))
    sentiment_score: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=sql_text("0.0")
    )
    intent: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'other'"))
    toxicity_score: Mapped[float] = mapped_column(
        Float, nullable=False, server_default=sql_text("0.0")
    )
    flags_json: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'[]'"))
    processed_at: Mapped[str] = mapped_column(Text, nullable=False)


class Entity(Base):
    __tablename__ = "entities"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_entities_project_name"),
        Index("idx_entities_project", "project_id"),
        Index("idx_entities_type", "type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'brand'"))
    sector: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    aliases_json: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'[]'"))
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'{}'"))
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    project: Mapped[ResearchProject] = relationship(back_populates="entities")
    mentions: Mapped[list[ContentEntityMention]] = relationship(back_populates="entity")


class ContentEntityMention(Base):
    __tablename__ = "content_entity_mentions"
    __table_args__ = (
        UniqueConstraint("project_id", "content_id", "entity_id", name="uq_mentions_project_content_entity"),
        Index("idx_mentions_project", "project_id"),
        Index("idx_mentions_content", "content_id"),
        Index("idx_mentions_entity", "entity_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=False
    )
    content_id: Mapped[int] = mapped_column(
        ForeignKey("social_contents.id", ondelete="CASCADE"), nullable=False
    )
    entity_id: Mapped[int] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
    )
    mention_text: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    confidence: Mapped[float] = mapped_column(Float, nullable=False, server_default=sql_text("0.0"))
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'rule'"))
    extracted_at: Mapped[str] = mapped_column(Text, nullable=False)

    project: Mapped[ResearchProject] = relationship(back_populates="entity_mentions")
    content: Mapped[SocialContent] = relationship(back_populates="entity_mentions")
    entity: Mapped[Entity] = relationship(back_populates="mentions")


class ContentAdSignal(Base):
    __tablename__ = "content_ad_signals"
    __table_args__ = (
        UniqueConstraint("project_id", "content_id", name="uq_content_ad_signals_project_content"),
        Index("idx_content_ad_signals_project", "project_id"),
        Index("idx_content_ad_signals_content", "content_id"),
        Index("idx_content_ad_signals_type", "project_id", "ad_type"),
        Index("idx_content_ad_signals_brand", "project_id", "brand_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=False
    )
    content_id: Mapped[int] = mapped_column(
        ForeignKey("social_contents.id", ondelete="CASCADE"), nullable=False
    )
    platform: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'YouTube'"))
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    ad_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'none'"))
    confidence: Mapped[float] = mapped_column(Float, nullable=False, server_default=sql_text("0.0"))
    disclosure_quality: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=sql_text("'not_applicable'")
    )
    is_commercial: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))
    is_disclosed: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))
    brand_name: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'[]'"))
    affiliate_signals_json: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'[]'"))
    sponsorship_signals_json: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'[]'"))
    risks_json: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'[]'"))
    detected_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    project: Mapped[ResearchProject] = relationship(back_populates="ad_signals")
    content: Mapped[SocialContent] = relationship(back_populates="ad_signals")


class ProcessingLog(Base):
    __tablename__ = "processing_logs"
    __table_args__ = (Index("idx_processing_logs_project", "project_id", sql_text("created_at DESC")),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    details_json: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'{}'"))
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class ApiUsage(Base):
    __tablename__ = "api_usage"
    __table_args__ = (
        UniqueConstraint("day", "operation", name="uq_api_usage_day_operation"),
        Index("idx_api_usage_day", "day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[str] = mapped_column(Text, nullable=False)
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    units: Mapped[int] = mapped_column(Integer, nullable=False, server_default=sql_text("0"))


class ContentTranscript(Base):
    __tablename__ = "content_transcripts"
    __table_args__ = (
        UniqueConstraint("project_id", "platform", "external_id", name="uq_transcripts_project_platform_external"),
        Index("idx_transcripts_project", "project_id"),
        Index("idx_transcripts_status", "project_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'YouTube'"))
    language: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'ok'"))
    error: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    text: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("''"))
    segments_json: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'[]'"))
    analysis_json: Mapped[str] = mapped_column(Text, nullable=False, server_default=sql_text("'{}'"))
    extracted_at: Mapped[str] = mapped_column(Text, nullable=False)
